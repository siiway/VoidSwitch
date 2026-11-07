package services

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/QuantumNous/new-api/relaykit/relayconvert"
	"github.com/QuantumNous/new-api/relaykit/relayconvert/convmeta"
	"github.com/QuantumNous/new-api/relaykit/types"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
	"github.com/siiway/voidswitch/internal/cryptoutil"
	"github.com/siiway/voidswitch/internal/database"
)

// InboundFormat maps an ApiStyle to a RelayKit format.
func InboundFormat(style string) types.RelayFormat {
	switch style {
	case string(constants.ApiStyleAnthropic):
		return types.RelayFormatClaude
	case string(constants.ApiStyleOpenAIResponses):
		return types.RelayFormatOpenAIResponses
	case string(constants.ApiStyleGemini):
		return types.RelayFormatGemini
	default:
		return types.RelayFormatOpenAI
	}
}

// UpstreamFormat maps a provider adapter style to a RelayKit format.
func UpstreamFormat(style constants.ApiStyle) types.RelayFormat {
	return InboundFormat(string(style))
}

// Candidate is one viable (upstream, key) pair for a request.
type Candidate struct {
	Provider     *database.Provider
	Upstream     *database.RouteUpstream
	Key          *database.ApiKey
	UpstreamModel string
}

// DispatchRequest is the input to the gateway dispatcher.
type DispatchRequest struct {
	Ctx           context.Context
	DB            *gorm.DB
	Cfg           *config.Settings
	Pool          *ClientPool
	ExposedModel  string
	InboundStyle  constants.ApiStyle
	Stream        bool
	Body          map[string]any
	Kind          RelayKind
	TokenID       *int
	UserSub       *string
}

// RelayKind is a coarse endpoint kind used for protocol conversion.
type RelayKind int

const (
	KindChat RelayKind = iota
	KindMessages
	KindResponses
)

// DispatchResult is the outcome of a gateway call.
type DispatchResult struct {
	StatusCode int
	Body       []byte
	Stream     io.ReadCloser // non-nil for streaming success
	Headers    http.Header
	Provider   *database.Provider
	Key        *database.ApiKey
	Upstream   string
}

// Dispatcher resolves a route and failovers across upstreams/keys.
type Dispatcher struct {
	req  *DispatchRequest
	seq  []Candidate
}

func NewDispatcher(req *DispatchRequest) *Dispatcher {
	return &Dispatcher{req: req}
}

// resolve builds the ordered candidate list for the exposed model. Phase 1
// honours group_position ordering, enabled flags, provider health ordering by
// node-latency is deferred; cooldowns are checked against upstream_cooldowns.
func (d *Dispatcher) resolve() error {
	db := d.req.DB
	var model database.ExposedModel
	if err := db.Where("model_id = ? AND enabled = ?", d.req.ExposedModel, true).First(&model).Error; err != nil {
		return fmt.Errorf("model not found: %w", err)
	}
	var route database.Route
	if err := db.Where("exposed_model_id = ?", model.ID).First(&route).Error; err != nil {
		return fmt.Errorf("no route for model %q: %w", d.req.ExposedModel, err)
	}
	var upstreams []database.RouteUpstream
	if err := db.Where("route_id = ? AND enabled = ?", route.ID, true).
		Order("group_position asc, position asc, weight desc").Find(&upstreams).Error; err != nil {
		return err
	}
	now := time.Now().UTC()
	var candidates []Candidate
	for i := range upstreams {
		u := &upstreams[i]
		if u.ProviderID == nil {
			continue
		}
		var provider database.Provider
		if err := db.Where("id = ? AND enabled = ?", *u.ProviderID, true).First(&provider).Error; err != nil {
			continue
		}
		if d.cooled(provider.ID, u.UpstreamModel, u.KeyPool, now) {
			continue
		}
		keys, err := d.candidateKeys(&provider, u.KeyPool, now)
		if err != nil || len(keys) == 0 {
			continue
		}
		for i := range keys {
			candidates = append(candidates, Candidate{
				Provider:      &provider,
				Upstream:      u,
				Key:           &keys[i],
				UpstreamModel: u.UpstreamModel,
			})
		}
	}
	if len(candidates) == 0 {
		return fmt.Errorf("no usable upstream/key for model %q", d.req.ExposedModel)
	}
	d.seq = candidates
	return nil
}

func (d *Dispatcher) cooled(providerID int, upstreamModel, pool string, now time.Time) bool {
	var count int64
	d.req.DB.Model(&database.UpstreamCooldown{}).
		Where("provider_id = ? AND upstream_model = ? AND key_pool = ? AND until > ?",
			providerID, upstreamModel, pool, now).Count(&count)
	return count > 0
}

func (d *Dispatcher) candidateKeys(p *database.Provider, pool string, now time.Time) ([]database.ApiKey, error) {
	q := d.req.DB.Where("provider_id = ? AND status = ?", p.ID, string(constants.KeyStatusActive))
	if pool != "" {
		q = q.Where("pool = ?", pool)
	}
	var keys []database.ApiKey
	if err := q.Order("sort_order asc, id asc").Find(&keys).Error; err != nil {
		return nil, err
	}
	// Filter out rate-limited keys still parked.
	out := keys[:0]
	for _, k := range keys {
		if k.RateLimitUntil != nil && k.RateLimitUntil.After(now) {
			continue
		}
		out = append(out, k)
	}
	return out, nil
}

// Do executes the dispatch, failovering over candidates. For streaming success it
// returns the upstream response body (SSE) already converted to the inbound
// style; callers copy it to the client.
func (d *Dispatcher) Do() (*DispatchResult, error) {
	if err := d.resolve(); err != nil {
		return nil, err
	}
	var lastErr error
	for _, cand := range d.seq {
		res, err := d.attempt(cand)
		if err != nil {
			lastErr = err
			continue
		}
		return res, nil
	}
	return nil, fmt.Errorf("all upstreams failed: %v", lastErr)
}

func (d *Dispatcher) attempt(cand Candidate) (*DispatchResult, error) {
	plainKey, err := cryptoutil.DecryptSecret(cand.Key.KeyCiphertext, d.req.Cfg.Server.SecretKey)
	if err != nil {
		return nil, fmt.Errorf("decrypt key: %w", err)
	}

	adapter := ResolveAdapter(cand.Provider)
	url := adapter.UpstreamURL()
	headers := adapter.Headers(plainKey, nil)

	upstreamBody, err := d.buildUpstreamBody(cand, adapter.GetStyle())
	if err != nil {
		return nil, err
	}
	raw, _ := json.Marshal(upstreamBody)

	route := NewRoute(nil, nil)
	client, err := d.req.Pool.Get(route, 15*time.Second, 300*time.Second)
	if err != nil {
		return nil, err
	}

	httpReq, err := http.NewRequestWithContext(d.req.Ctx, http.MethodPost, url, bytes.NewReader(raw))
	if err != nil {
		return nil, err
	}
	for k, v := range headers {
		httpReq.Header.Set(k, v)
	}
	if d.req.Stream {
		httpReq.Header.Set("Accept", "text/event-stream")
	}

	resp, err := client.Do(httpReq)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		defer resp.Body.Close()
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
		d.noteFailure(cand, resp.StatusCode)
		return nil, fmt.Errorf("upstream %s returned %d: %s", cand.Provider.Name, resp.StatusCode, truncate(string(b), 300))
	}

	d.noteSuccess(cand)

	upstreamFormat := UpstreamFormat(adapter.GetStyle())
	inboundFormat := InboundFormat(string(d.req.InboundStyle))

	if d.req.Stream {
		stream := d.convertStream(resp.Body, upstreamFormat, inboundFormat, cand.UpstreamModel)
		return &DispatchResult{
			StatusCode: http.StatusOK, Stream: stream, Headers: resp.Header,
			Provider: cand.Provider, Key: cand.Key, Upstream: cand.UpstreamModel,
		}, nil
	}

	defer resp.Body.Close()
	bodyBytes, _ := io.ReadAll(resp.Body)
	outBody, err := d.convertResponse(bodyBytes, upstreamFormat, inboundFormat, cand.UpstreamModel)
	if err != nil {
		return nil, err
	}
	return &DispatchResult{
		StatusCode: http.StatusOK, Body: outBody, Headers: resp.Header,
		Provider: cand.Provider, Key: cand.Key, Upstream: cand.UpstreamModel,
	}, nil
}

func (d *Dispatcher) buildUpstreamBody(cand Candidate, upstreamStyle constants.ApiStyle) (map[string]any, error) {
	inbound := parseRequestDTO(d.req.Body, d.req.InboundStyle)
	target := UpstreamFormat(upstreamStyle)
	meta := &convmeta.Values{
		OriginModelName:   d.req.ExposedModel,
		UpstreamModelName: cand.UpstreamModel,
		ChannelMetaAttached: true,
	}
	res, err := relayconvert.ConvertRequest(d.req.Ctx, meta, target, inbound)
	if err != nil {
		return nil, fmt.Errorf("convert request: %w", err)
	}
	raw, err := json.Marshal(res.Value)
	if err != nil {
		return nil, err
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, err
	}
	// Ensure model is the upstream model.
	out["model"] = cand.UpstreamModel
	if adapter := ResolveAdapter(cand.Provider); adapter != nil {
		out = adapter.PrepareBody(out)
	}
	return out, nil
}

func (d *Dispatcher) convertResponse(raw []byte, from, to types.RelayFormat, model string) ([]byte, error) {
	respDTO, err := parseResponseDTO(raw, from)
	if err != nil {
		return nil, err
	}
	meta := &convmeta.Values{OriginModelName: d.req.ExposedModel, UpstreamModelName: model, ChannelMetaAttached: true}
	res, err := relayconvert.ConvertResponse(d.req.Ctx, meta, to, respDTO)
	if err != nil {
		return nil, fmt.Errorf("convert response: %w", err)
	}
	return json.Marshal(res.Value)
}

func (d *Dispatcher) convertStream(body io.ReadCloser, from, to types.RelayFormat, model string) io.ReadCloser {
	pr, pw := io.Pipe()
	go func() {
		defer body.Close()
		defer pw.Close()
		state, err := relayconvert.NewResponseStreamState(from, to, relayconvert.ResponseStreamOptions{
			Model:        d.req.ExposedModel,
			IncludeUsage: true,
		})
		if err != nil {
			_ = pw.CloseWithError(err)
			return
		}
		dec := newSSEReader(body)
		meta := &convmeta.Values{OriginModelName: d.req.ExposedModel, UpstreamModelName: model, ChannelMetaAttached: true}
		for {
			data, event, ok := dec.Next()
			if !ok {
				break
			}
			chunkDTO, err := parseStreamChunk(data, event, from)
			if err != nil || chunkDTO == nil {
				continue
			}
			results, err := relayconvert.ConvertStreamResponseChunk(d.req.Ctx, meta, state, chunkDTO)
			if err != nil {
				continue
			}
			for _, r := range results {
				if b, err := json.Marshal(r.Value); err == nil {
					writeSSE(pw, b)
				}
			}
		}
		if finals, err := relayconvert.FinalizeStreamResponse(d.req.Ctx, meta, state); err == nil {
			for _, r := range finals {
				if b, err := json.Marshal(r.Value); err == nil {
					writeSSE(pw, b)
				}
			}
		}
		pw.Write([]byte("data: [DONE]\n\n"))
	}()
	return pr
}

func (d *Dispatcher) noteFailure(cand Candidate, status int) {
	db := d.req.DB
	_ = db.Model(&database.ApiKey{}).Where("id = ?", cand.Key.ID).
		UpdateColumn("failed_count", gorm.Expr("failed_count + 1")).Error
	// Simple cooldown on 429/5xx per route upstream config (default 180s).
	codes := []int{}
	database.DecodeJSON(cand.Upstream.CooldownStatusCodes, &codes)
	if len(codes) == 0 {
		codes = []int{0, 429, 500, 502, 503, 504}
	}
	if containsInt(codes, status) {
		secs := cand.Upstream.CooldownSeconds
		if secs <= 0 {
			secs = GetInt("upstream_cooldown_seconds", 180)
		}
		until := time.Now().UTC().Add(time.Duration(secs) * time.Second)
		cd := database.UpstreamCooldown{
			ProviderID: cand.Provider.ID, UpstreamModel: cand.UpstreamModel,
			KeyPool: cand.Upstream.KeyPool, Until: until,
			TriggerStatus: status, TriggerSource: "global", TriggeredAt: time.Now().UTC(),
		}
		_ = db.Where("provider_id = ? AND upstream_model = ? AND key_pool = ?",
			cand.Provider.ID, cand.UpstreamModel, cand.Upstream.KeyPool).FirstOrCreate(&cd).Error
		_ = db.Model(&database.UpstreamCooldown{}).
			Where("provider_id = ? AND upstream_model = ? AND key_pool = ?",
				cand.Provider.ID, cand.UpstreamModel, cand.Upstream.KeyPool).
			Updates(map[string]any{"until": until, "trigger_status": status, "triggered_at": time.Now().UTC()}).Error
	}
}

func (d *Dispatcher) noteSuccess(cand Candidate) {
	now := time.Now().UTC()
	db := d.req.DB
	_ = db.Model(&database.ApiKey{}).Where("id = ?", cand.Key.ID).
		Updates(map[string]any{"failed_count": 0, "last_used_at": now}).Error
	_ = db.Where("provider_id = ? AND upstream_model = ? AND key_pool = ?",
		cand.Provider.ID, cand.UpstreamModel, cand.Upstream.KeyPool).
		Delete(&database.UpstreamCooldown{}).Error
}

func containsInt(s []int, v int) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}

// ---- DTO parsing helpers --------------------------------------------------

func parseRequestDTO(body map[string]any, style constants.ApiStyle) any {
	raw, _ := json.Marshal(body)
	switch style {
	case constants.ApiStyleAnthropic:
		var req dto.ClaudeRequest
		_ = json.Unmarshal(raw, &req)
		return &req
	case constants.ApiStyleOpenAIResponses:
		var req dto.OpenAIResponsesRequest
		_ = json.Unmarshal(raw, &req)
		return &req
	case constants.ApiStyleGemini:
		var req dto.GeminiChatRequest
		_ = json.Unmarshal(raw, &req)
		return &req
	default:
		var req dto.GeneralOpenAIRequest
		_ = json.Unmarshal(raw, &req)
		return &req
	}
}

func parseResponseDTO(raw []byte, from types.RelayFormat) (any, error) {
	switch from {
	case types.RelayFormatClaude:
		var r dto.ClaudeResponse
		if err := json.Unmarshal(raw, &r); err != nil {
			return nil, err
		}
		return &r, nil
	case types.RelayFormatOpenAIResponses:
		var r dto.OpenAIResponsesResponse
		if err := json.Unmarshal(raw, &r); err != nil {
			return nil, err
		}
		return &r, nil
	case types.RelayFormatGemini:
		var r dto.GeminiChatResponse
		if err := json.Unmarshal(raw, &r); err != nil {
			return nil, err
		}
		return &r, nil
	default:
		var r dto.OpenAITextResponse
		if err := json.Unmarshal(raw, &r); err != nil {
			return nil, err
		}
		return &r, nil
	}
}

func parseStreamChunk(data, event string, from types.RelayFormat) (any, error) {
	switch from {
	case types.RelayFormatClaude:
		var c dto.ClaudeResponse
		if err := json.Unmarshal([]byte(data), &c); err != nil {
			return nil, err
		}
		return &c, nil
	case types.RelayFormatOpenAIResponses:
		var c dto.ResponsesStreamResponse
		if err := json.Unmarshal([]byte(data), &c); err != nil {
			return nil, err
		}
		return &c, nil
	case types.RelayFormatGemini:
		var c dto.GeminiChatResponse
		if err := json.Unmarshal([]byte(data), &c); err != nil {
			return nil, err
		}
		return &c, nil
	default:
		var c dto.ChatCompletionsStreamResponse
		if err := json.Unmarshal([]byte(data), &c); err != nil {
			return nil, err
		}
		return &c, nil
	}
}

func writeSSE(w io.Writer, data []byte) {
	_, _ = w.Write([]byte("data: "))
	_, _ = w.Write(data)
	_, _ = w.Write([]byte("\n\n"))
}

// sseReader is a minimal SSE line parser.
type sseReader struct {
	r    *bufio.Reader
	done bool
}

func newSSEReader(r io.Reader) *sseReader {
	return &sseReader{r: bufio.NewReader(r)}
}

func (s *sseReader) Next() (data, event string, ok bool) {
	var dataLines []string
	for {
		line, err := s.r.ReadString('\n')
		if err != nil && line == "" {
			return "", "", false
		}
		line = strings.TrimRight(line, "\r\n")
		if line == "" {
			if len(dataLines) > 0 {
				return strings.Join(dataLines, "\n"), event, true
			}
			if err != nil {
				return "", "", false
			}
			continue
		}
		if strings.HasPrefix(line, "data:") {
			dataLines = append(dataLines, strings.TrimSpace(strings.TrimPrefix(line, "data:")))
		} else if strings.HasPrefix(line, "event:") {
			event = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		}
		if err != nil {
			if len(dataLines) > 0 {
				return strings.Join(dataLines, "\n"), event, true
			}
			return "", "", false
		}
	}
}
