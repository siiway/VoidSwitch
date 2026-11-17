package services

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptrace"
	"strings"
	"time"

	"github.com/QuantumNous/new-api/relaykit/dto"
	"github.com/QuantumNous/new-api/relaykit/relayconvert"
	"github.com/QuantumNous/new-api/relaykit/relayconvert/convmeta"
	"github.com/QuantumNous/new-api/relaykit/types"
	"gorm.io/gorm"

	"github.com/siiway/voidswitch/internal/config"
	"github.com/siiway/voidswitch/internal/constants"
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
	Provider      *database.Provider
	Upstream      *database.RouteUpstream
	Key           *database.ApiKey
	UpstreamModel string
}

// DispatchRequest is the input to the gateway dispatcher.
type DispatchRequest struct {
	Ctx          context.Context
	DB           *gorm.DB
	Cfg          *config.Settings
	Pool         *ClientPool
	ExposedModel string
	InboundStyle constants.ApiStyle
	Stream       bool
	Body         map[string]any
	Kind         RelayKind
	TokenID      *int
	UserSub      *string
	// Debug captures request/response bodies (and streamed SSE) into the
	// per-attempt trail. Headers and the routing chain are always recorded.
	Debug bool
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
	// UpstreamStyle is the provider's API style (e.g. "anthropic"), so the log
	// records the real inbound→upstream protocol pair.
	UpstreamStyle string
	Usage         Usage
	// UsageReady is closed when a streaming response has fully drained and Usage
	// is final (non-stream results set it before returning).
	UsageReady chan struct{}
}

// Usage holds token accounting for one request.
type Usage struct {
	PromptTokens     int64
	CompletionTokens int64
	TotalTokens      int64
	FirstTokenMs     *float64
}

// claudeDefaultMaxTokens is the max_tokens injected when an OpenAI-style request
// is converted for a Claude upstream and the model declares no output cap. The
// Claude Messages API rejects requests without max_tokens; 8192 is the relay
// default (new-api uses the same), overridable per model via limit_output.
const claudeDefaultMaxTokens = 8192

// Dispatcher resolves a route and failovers across upstreams/keys.
type Dispatcher struct {
	req          *DispatchRequest
	seq          []Candidate
	egressNodeID int
	maxTokens    int
	attempts     []*AttemptRecord
}

func NewDispatcher(req *DispatchRequest) *Dispatcher {
	return &Dispatcher{req: req}
}

// Attempts returns the recorded failover trail in chronological order. It is
// valid after Do() returns, whether the dispatch succeeded or exhausted every
// candidate.
func (d *Dispatcher) Attempts() []*AttemptRecord { return d.attempts }

// ParsePassthroughEntry splits a passthrough whitelist entry into its parts.
// The grammar is "exposed [=> upstream] [@ pool]": the exposed id is what
// callers use, `upstream` overrides the id sent to the provider, and `pool`
// selects a key pool. A bare entry uses the exposed id for both.
func ParsePassthroughEntry(entry string) (exposed, upstream, pool string) {
	e := strings.TrimSpace(entry)
	exposed, upstream = e, e
	if i := strings.Index(e, "=>"); i >= 0 {
		exposed = strings.TrimSpace(e[:i])
		rest := strings.TrimSpace(e[i+2:])
		upstream = rest
		if j := strings.Index(rest, "@"); j >= 0 {
			upstream = strings.TrimSpace(rest[:j])
			pool = strings.TrimSpace(rest[j+1:])
		}
	} else if j := strings.Index(e, "@"); j >= 0 {
		exposed = strings.TrimSpace(e[:j])
		upstream = exposed
		pool = strings.TrimSpace(e[j+1:])
	}
	return exposed, upstream, pool
}

// resolvePassthrough matches a "provider-slug/exposed-model-id" request against
// the providers' passthrough whitelists. Passthrough models bypass the exposed
// model + route system and dispatch straight to one provider, so they get a
// single synthetic candidate. Returns nil when the id is not a passthrough id.
func (d *Dispatcher) resolvePassthrough(model string) (*Candidate, error) {
	i := strings.Index(model, "/")
	if i <= 0 {
		return nil, nil
	}
	slug, exposedID := model[:i], model[i+1:]
	var provider database.Provider
	if err := d.req.DB.Where("slug = ?", slug).First(&provider).Error; err != nil {
		return nil, nil
	}
	if !provider.PassthroughEnabled {
		return nil, nil
	}
	var list []string
	database.DecodeJSON(provider.PassthroughModels, &list)
	for _, entry := range list {
		exposed, upstream, pool := ParsePassthroughEntry(entry)
		if exposed != exposedID {
			continue
		}
		if !provider.Enabled {
			return nil, fmt.Errorf("provider for %q is disabled", model)
		}
		if upstream == "" {
			upstream = exposedID
		}
		return &Candidate{
			Provider:      &provider,
			Upstream:      passthroughUpstream(&provider, upstream, pool),
			UpstreamModel: upstream,
		}, nil
	}
	return nil, fmt.Errorf("model %q is not in this provider's passthrough list", model)
}

// passthroughUpstream builds the synthetic route-upstream a passthrough model
// dispatches through, so the rest of the dispatch path (body rewriting, cooldown
// bookkeeping) sees the same shape as a routed model.
func passthroughUpstream(p *database.Provider, upstreamModel, pool string) *database.RouteUpstream {
	id := p.ID
	return &database.RouteUpstream{
		ProviderID:    &id,
		UpstreamModel: upstreamModel,
		KeyPool:       pool,
		Enabled:       true,
		Weight:        1,
	}
}

// resolve builds the ordered candidate list for the exposed model. Phase 1
// honours group_position ordering, enabled flags, provider health ordering by
// node-latency is deferred; cooldowns are checked against upstream_cooldowns.
func (d *Dispatcher) resolve() error {
	db := d.req.DB

	// Resolution order matches resolvePublicModel in the handlers package: an
	// exposed row *with a route* wins, so an admin's own model keeps its route;
	// otherwise a passthrough whitelist match serves the request; otherwise the
	// row (if any) is used and the missing route is reported.
	var model database.ExposedModel
	exposedErr := db.Where("model_id = ? AND enabled = ?", d.req.ExposedModel, true).First(&model).Error
	routed := false
	if exposedErr == nil {
		var route database.Route
		routed = db.Where("exposed_model_id = ?", model.ID).First(&route).Error == nil
	}

	if !routed {
		// Passthrough ids (provider-slug/model) bypass the exposed-model + route
		// system and dispatch to a single provider.
		if cand, err := d.resolvePassthrough(d.req.ExposedModel); err != nil {
			return err
		} else if cand != nil {
			now := time.Now().UTC()
			keys, kerr := d.candidateKeys(cand.Provider, cand.Upstream.KeyPool, now)
			if kerr != nil || len(keys) == 0 {
				return fmt.Errorf("no usable key for model %q", d.req.ExposedModel)
			}
			d.seq = make([]Candidate, 0, len(keys))
			for i := range keys {
				d.seq = append(d.seq, Candidate{
					Provider:      cand.Provider,
					Upstream:      cand.Upstream,
					Key:           &keys[i],
					UpstreamModel: cand.UpstreamModel,
				})
			}
			return nil
		}
	}

	if exposedErr != nil {
		return fmt.Errorf("model not found: %w", exposedErr)
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
		// "200 OK + 0 tokens" auto-retry: when the provider opts in, a non-stream
		// success that produced no tokens is a degenerate upstream result — count
		// it as a failure and try the next candidate rather than delivering an
		// empty reply.
		if cand.Provider.RetryOnZeroToken && !d.req.Stream && res.Usage.TotalTokens == 0 {
			d.noteFailure(cand, 200)
			// Mark the attempt so the trail explains why a 200 was retried.
			if n := len(d.attempts); n > 0 {
				d.attempts[n-1].Error = strPtr("upstream returned 200 OK with 0 tokens")
			}
			lastErr = fmt.Errorf("upstream %s returned 200 OK with 0 tokens", cand.Provider.Name)
			continue
		}
		return res, nil
	}
	return nil, fmt.Errorf("all upstreams failed: %v", lastErr)
}

func (d *Dispatcher) attempt(cand Candidate) (*DispatchResult, error) {
	n := len(d.attempts) + 1
	rec := &AttemptRecord{
		Attempt:         n,
		ProviderAttempt: intPtr(n),
		Method:          strPtr(http.MethodPost),
		Provider:        strPtr(cand.Provider.Name),
		ProviderID:      intPtr(cand.Provider.ID),
		KeyID:           intPtr(cand.Key.ID),
		KeyPreview:      strPtr(cand.Key.KeyPreview),
		Pool:            nullableString(cand.Upstream.KeyPool),
		UpstreamModel:   strPtr(cand.UpstreamModel),
	}
	start := time.Now()
	// Register the append first so it runs last: the recording helpers below
	// mutate the same pointer the deferred append captures.
	defer func() { d.attempts = append(d.attempts, rec) }()

	recordDuration := func() {
		dur := float64(time.Since(start).Milliseconds())
		rec.DurationMs = &dur
		if len(rec.NetworkAttempts) > 0 {
			rec.NetworkAttempts[0].DurationMs = &dur
		}
	}

	plainKey, err := ResolveCredential(d.req.DB, cand.Provider, cand.Key, d.req.Cfg.Server.SecretKey)
	if err != nil {
		recordDuration()
		rec.Error = strPtr("resolve credential: " + err.Error())
		return nil, fmt.Errorf("resolve credential: %w", err)
	}

	adapter := ResolveAdapter(cand.Provider)
	url := adapter.UpstreamURL()
	headers := adapter.Headers(plainKey, nil)
	rec.URL = strPtr(url)
	rec.ReqHeaders = redactRequestHeaders(headers)
	if d.req.Stream {
		if rec.ReqHeaders == nil {
			rec.ReqHeaders = map[string]string{}
		}
		rec.ReqHeaders["Accept"] = "text/event-stream"
	}

	upstreamBody, err := d.buildUpstreamBody(cand, adapter.GetStyle())
	if err != nil {
		recordDuration()
		rec.Error = strPtr(err.Error())
		return nil, err
	}
	raw, _ := json.Marshal(upstreamBody)
	if d.req.Debug {
		rec.ReqBody = captureValue(upstreamBody, logBodyCaptureMax())
	}

	egress := ResolveEgress(d.req.DB, cand.Provider, d.req.Cfg.Server.SecretKey)
	d.egressNodeID = egress.NodeID
	rec.ProxyURL = egress.ProxyURL
	rec.LocalAddress = egress.LocalAddress
	rec.RouteType = strPtr(routeTypeOf(egress))
	// ConnectMs measures getting a usable upstream connection (DNS + TCP + TLS),
	// which is what the log's "latency" column means now that "duration" already
	// covers the whole request. It is recorded even when the dial fails, so a
	// timeout shows how long it waited instead of a blank cell.
	var connectTracker *connectTrace
	rec.NetworkAttempts = []NetworkAttempt{{
		Attempt:   1,
		NodeID:    intPtrOrNil(egress.NodeID),
		RouteType: strPtr(routeTypeOf(egress)),
	}}

	var resp *http.Response
	if egress.NodeKind == "agent" {
		h := headers
		if d.req.Stream {
			h["Accept"] = "text/event-stream"
		}
		resp, err = SendThroughAgent(d.req.Ctx, egress, http.MethodPost, url, h, raw, 300*time.Second)
		if err != nil {
			recordDuration()
			rec.NetworkError = true
			msg := redactEgressText(err.Error(), egress)
			rec.Error = strPtr(msg)
			rec.NetworkAttempts[0].Error = strPtr(msg)
			d.recordNodeHealth(egress.NodeID, false, 0)
			return nil, fmt.Errorf("%s", msg)
		}
	} else {
		route := NewRoute(egress.ProxyURL, egress.LocalAddress)
		client, cerr := d.req.Pool.Get(route, 15*time.Second, 300*time.Second)
		if cerr != nil {
			recordDuration()
			msg := redactEgressText(cerr.Error(), egress)
			rec.Error = strPtr(msg)
			rec.NetworkAttempts[0].Error = strPtr(msg)
			rec.NetworkAttempts[0].PoolTimeout = true
			return nil, fmt.Errorf("%s", msg)
		}
		httpReq, berr := http.NewRequestWithContext(d.req.Ctx, http.MethodPost, url, bytes.NewReader(raw))
		if berr != nil {
			recordDuration()
			rec.Error = strPtr(berr.Error())
			rec.NetworkAttempts[0].Error = strPtr(berr.Error())
			return nil, berr
		}
		for k, v := range headers {
			httpReq.Header.Set(k, v)
		}
		if d.req.Stream {
			httpReq.Header.Set("Accept", "text/event-stream")
		}
		startNet := time.Now()
		connectTracker = &connectTrace{start: startNet}
		resp, err = client.Do(httpReq.WithContext(httptrace.WithClientTrace(httpReq.Context(), connectTracker.trace())))
		rec.ConnectMs = connectTracker.elapsed()
		if err != nil {
			recordDuration()
			rec.NetworkError = true
			msg := redactEgressText(err.Error(), egress)
			rec.Error = strPtr(msg)
			rec.NetworkAttempts[0].Error = strPtr(msg)
			d.recordNodeHealth(egress.NodeID, false, 0)
			return nil, fmt.Errorf("%s", msg)
		}
		d.recordNodeHealth(egress.NodeID, true, float64(time.Since(startNet).Milliseconds()))
	}
	rec.NetworkAttempts[0].StatusCode = intPtr(resp.StatusCode)

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		defer resp.Body.Close()
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
		// Some upstreams echo the credential back in the error (e.g. OpenAI's
		// "Incorrect API key provided: sk-…"); never persist or return it.
		b = []byte(redactSecrets(string(b), plainKey))
		recordDuration()
		rec.StatusCode = intPtr(resp.StatusCode)
		rec.ErrorClass = strPtr(string(adapter.Classify(resp.StatusCode, nil)))
		rec.RespHeaders = redactedResponseHeaders(resp.Header)
		// An error body carries the provider's real reason, so capture it even
		// when the token has debug off (still capped by the same setting).
		rec.RespBody = captureBody(b, logBodyCaptureMax())
		errMsg := redactSecrets(fmt.Sprintf("upstream %s returned %d: %s", cand.Provider.Name, resp.StatusCode, truncate(string(b), 300)), plainKey)
		rec.Error = strPtr(errMsg)
		d.noteFailure(cand, resp.StatusCode)
		return nil, fmt.Errorf("%s", errMsg)
	}

	d.noteSuccess(cand)
	rec.StatusCode = intPtr(resp.StatusCode)
	rec.ErrorClass = strPtr("ok")
	rec.RespHeaders = redactedResponseHeaders(resp.Header)

	upstreamFormat := UpstreamFormat(adapter.GetStyle())
	inboundFormat := InboundFormat(string(d.req.InboundStyle))

	if d.req.Stream {
		streamBody := io.ReadCloser(resp.Body)
		if d.req.Debug {
			rec.respCapture = newBodyCapture(logBodyCaptureMax())
			streamBody = &captureReader{src: resp.Body, c: rec.respCapture}
		}
		stream := d.convertStream(streamBody, upstreamFormat, inboundFormat, cand.UpstreamModel)
		ready := make(chan struct{})
		res := &DispatchResult{
			StatusCode: http.StatusOK, Stream: stream, Headers: resp.Header,
			Provider: cand.Provider, Key: cand.Key, Upstream: cand.UpstreamModel,
			UpstreamStyle: string(adapter.GetStyle()),
			UsageReady:    ready,
		}
		// Tee the converted downstream SSE to accumulate usage + first-token time.
		res.Stream = newUsageTee(stream, res, ready)
		recordDuration()
		return res, nil
	}

	defer resp.Body.Close()
	bodyBytes, _ := io.ReadAll(resp.Body)
	recordDuration()
	if d.req.Debug {
		rec.RespBody = captureBody(bodyBytes, logBodyCaptureMax())
	}
	outBody, err := d.convertResponse(bodyBytes, upstreamFormat, inboundFormat, cand.UpstreamModel)
	if err != nil {
		rec.Error = strPtr(err.Error())
		return nil, err
	}
	usage := extractUsage(bodyBytes)
	rec.PromptTokens = usage.PromptTokens
	rec.CompletionTokens = usage.CompletionTokens
	rec.TotalTokens = usage.TotalTokens
	return &DispatchResult{
		StatusCode: http.StatusOK, Body: outBody, Headers: resp.Header,
		Provider: cand.Provider, Key: cand.Key, Upstream: cand.UpstreamModel,
		UpstreamStyle: string(adapter.GetStyle()),
		Usage:         usage,
	}, nil
}

func (d *Dispatcher) buildUpstreamBody(cand Candidate, upstreamStyle constants.ApiStyle) (map[string]any, error) {
	inbound := parseRequestDTO(d.req.Body, d.req.InboundStyle)
	target := UpstreamFormat(upstreamStyle)
	meta := &convmeta.Values{
		OriginModelName:     d.req.ExposedModel,
		UpstreamModelName:   cand.UpstreamModel,
		ChannelMetaAttached: true,
		Options: &convmeta.Options{
			Claude: convmeta.ClaudeOptions{
				DefaultMaxTokens: func(string) int { return d.defaultMaxTokens() },
			},
		},
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
	// OpenAI-style upstreams: optionally remap role "developer" -> "system"
	// (per-provider toggle, default on) so older upstreams don't reject it.
	if upstreamStyle == constants.ApiStyleOpenAI && cand.Provider.NormalizeDeveloperRoleToSystem {
		normalizeDeveloperRoles(out)
	}
	if adapter := ResolveAdapter(cand.Provider); adapter != nil {
		out = adapter.PrepareBody(out)
	}
	return out, nil
}

// defaultMaxTokens resolves the max_tokens injected when an OpenAI-style request
// reaches a Claude upstream without one: the exposed model's configured output
// cap (limit_output), else claudeDefaultMaxTokens. The result is cached for the
// request so failover attempts do not re-read the model row.
func (d *Dispatcher) defaultMaxTokens() int {
	if d.maxTokens > 0 {
		return d.maxTokens
	}
	d.maxTokens = claudeDefaultMaxTokens
	var m database.ExposedModel
	if err := d.req.DB.Select("limit_output").Where("model_id = ?", d.req.ExposedModel).
		Limit(1).Find(&m).Error; err != nil {
		slog.Warn("default max tokens lookup failed", "model", d.req.ExposedModel, "err", err)
	} else if m.LimitOutput != nil && *m.LimitOutput > 0 {
		d.maxTokens = *m.LimitOutput
	}
	return d.maxTokens
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

// recordNodeHealth updates a node's EWMA latency + failure count and appends a
// health sample (used by the health-history view).
func (d *Dispatcher) recordNodeHealth(nodeID int, success bool, latencyMs float64) {
	if nodeID == 0 {
		return
	}
	db := d.req.DB
	now := time.Now().UTC()

	if success {
		halfLife := GetFloat("node_rank_ewma_half_life_seconds", 300)
		alpha := 0.3
		if halfLife > 0 {
			alpha = 1 - 0.5*(1/(halfLife/60)) // coarse convergence; bounded below
			if alpha < 0.2 {
				alpha = 0.2
			}
			if alpha > 0.8 {
				alpha = 0.8
			}
		}
		var node database.Node
		if err := db.First(&node, nodeID).Error; err == nil {
			newEWMA := latencyMs
			if node.LatencyEWMA != nil {
				newEWMA = alpha*latencyMs + (1-alpha)*(*node.LatencyEWMA)
			}
			db.Model(&node).Updates(map[string]any{
				"latency_ewma": newEWMA, "latency_ms": latencyMs, "failed_count": 0,
				"last_checked_at": now, "status": string(constants.NodeStatusActive),
			})
		}
	} else {
		db.Model(&database.Node{}).Where("id = ?", nodeID).
			Updates(map[string]any{"last_checked_at": now, "failed_count": gorm.Expr("failed_count + 1")})
	}

	sample := database.NodeHealthSample{
		NodeID: nodeID, TS: now, Source: "request", Success: success,
	}
	if latencyMs > 0 {
		sample.LatencyMs = &latencyMs
	}
	db.Create(&sample)
}

// normalizeDeveloperRoles rewrites OpenAI "developer" role messages to "system".
func normalizeDeveloperRoles(body map[string]any) {
	msgs, ok := body["messages"].([]any)
	if !ok {
		return
	}
	for _, m := range msgs {
		if mm, ok := m.(map[string]any); ok {
			if r, _ := mm["role"].(string); r == "developer" {
				mm["role"] = "system"
			}
		}
	}
}
