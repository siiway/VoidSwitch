package services

import (
	"encoding/json"
	"io"
	"sync"
	"time"
)

// extractUsage pulls token counts from a non-stream OpenAI/Anthropic-style
// response body (best-effort; returns zeros when absent).
func extractUsage(raw []byte) Usage {
	var body struct {
		Usage map[string]any `json:"usage"`
	}
	if json.Unmarshal(raw, &body) != nil || body.Usage == nil {
		return Usage{}
	}
	u := body.Usage
	u = flattenUsage(u)
	return Usage{
		PromptTokens:     intOf(u["prompt_tokens"], u["input_tokens"]),
		CompletionTokens: intOf(u["completion_tokens"], u["output_tokens"]),
		TotalTokens:      intOf(u["total_tokens"]),
	}
}

func flattenUsage(u map[string]any) map[string]any {
	return u
}

func intOf(vals ...any) int64 {
	for _, v := range vals {
		switch n := v.(type) {
		case float64:
			if n != 0 {
				return int64(n)
			}
		case int64:
			if n != 0 {
				return n
			}
		case int:
			if n != 0 {
				return int64(n)
			}
		}
	}
	return 0
}

// usageTee wraps a downstream SSE stream, sniffing usage + first-token timing
// as bytes flow to the client, and finalises Usage on close.
type usageTee struct {
	src   io.ReadCloser
	res   *DispatchResult
	ready chan struct{}
	once  sync.Once

	start      time.Time
	firstToken *float64
	usage      Usage
	buf        []byte
	mu         sync.Mutex
}

func newUsageTee(src io.ReadCloser, res *DispatchResult, ready chan struct{}) *usageTee {
	return &usageTee{src: src, res: res, ready: ready, start: time.Now()}
}

func (t *usageTee) Read(p []byte) (int, error) {
	n, err := t.src.Read(p)
	if n > 0 {
		t.mu.Lock()
		t.buf = append(t.buf, p[:n]...)
		t.inspect()
		t.mu.Unlock()
	}
	if err != nil {
		t.finish()
	}
	return n, err
}

func (t *usageTee) Close() error {
	err := t.src.Close()
	t.finish()
	return err
}

func (t *usageTee) finish() {
	t.once.Do(func() {
		t.mu.Lock()
		t.inspect()
		t.usage.FirstTokenMs = t.firstToken
		t.res.Usage = t.usage
		t.mu.Unlock()
		close(t.ready)
	})
}

// inspect scans complete SSE "data:" lines already buffered for usage + first
// token markers, then trims consumed bytes.
func (t *usageTee) inspect() {
	for {
		idx := indexLine(t.buf)
		if idx < 0 {
			return
		}
		line := string(t.buf[:idx])
		t.buf = t.buf[idx+1:]
		line = trimPrefix(line, "data:")
		line = trimSpace(line)
		if line == "" || line == "[DONE]" {
			continue
		}
		var frame map[string]any
		if json.Unmarshal([]byte(line), &frame) != nil {
			continue
		}
		if t.firstToken == nil && hasContent(frame) {
			ms := float64(time.Since(t.start).Milliseconds())
			t.firstToken = &ms
		}
		if u, ok := frame["usage"].(map[string]any); ok && u != nil {
			if pt := intOf(u["prompt_tokens"], u["input_tokens"]); pt > 0 {
				t.usage.PromptTokens = pt
			}
			if ct := intOf(u["completion_tokens"], u["output_tokens"]); ct > 0 {
				t.usage.CompletionTokens = ct
			}
			if tt := intOf(u["total_tokens"]); tt > 0 {
				t.usage.TotalTokens = tt
			}
		}
		if m, ok := frame["message"].(map[string]any); ok {
			if u, ok := m["usage"].(map[string]any); ok && u != nil {
				t.usage.PromptTokens = intOf(u["input_tokens"], u["prompt_tokens"])
				t.usage.CompletionTokens = intOf(u["output_tokens"], u["completion_tokens"])
			}
		}
	}
}

func indexLine(b []byte) int {
	for i, c := range b {
		if c == '\n' {
			return i
		}
	}
	return -1
}

func trimPrefix(s, p string) string {
	if len(s) >= len(p) && s[:len(p)] == p {
		return s[len(p):]
	}
	return s
}

func trimSpace(s string) string {
	for len(s) > 0 && (s[0] == ' ' || s[0] == '\t' || s[0] == '\r') {
		s = s[1:]
	}
	for len(s) > 0 && (s[len(s)-1] == ' ' || s[len(s)-1] == '\t' || s[len(s)-1] == '\r') {
		s = s[:len(s)-1]
	}
	return s
}

// hasContent reports whether a streamed frame carries user-visible output
// (content/reasoning delta or a non-empty text block).
func hasContent(frame map[string]any) bool {
	if choices, ok := frame["choices"].([]any); ok {
		for _, c := range choices {
			if cm, ok := c.(map[string]any); ok {
				if d, ok := cm["delta"].(map[string]any); ok {
					if s, ok := d["content"].(string); ok && s != "" {
						return true
					}
					if s, ok := d["reasoning_content"].(string); ok && s != "" {
						return true
					}
				}
			}
		}
	}
	if t, ok := frame["type"].(string); ok {
		if t == "content_block_delta" {
			return true
		}
	}
	return false
}

// ensure bufio stays imported for future SSE needs
