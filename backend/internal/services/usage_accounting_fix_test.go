package services

import (
	"io"
	"strings"
	"testing"
	"time"
)

// Anthropic non-stream body: input/output tokens, no total_tokens.
func TestExtractUsageAnthropicNoTotal(t *testing.T) {
	raw := []byte(`{"type":"message","usage":{"input_tokens":727,"output_tokens":192}}`)
	u := extractUsage(raw)
	if u.PromptTokens != 727 || u.CompletionTokens != 192 {
		t.Fatalf("parts: %+v", u)
	}
	if u.TotalTokens != 919 {
		t.Fatalf("total = %d, want 919", u.TotalTokens)
	}
}

// OpenAI body that does carry total_tokens must be left alone.
func TestExtractUsageOpenAITotalKept(t *testing.T) {
	raw := []byte(`{"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":99}}`)
	u := extractUsage(raw)
	if u.TotalTokens != 99 {
		t.Fatalf("total = %d, want 99", u.TotalTokens)
	}
}

// Anthropic SSE stream: message_start carries input_tokens, message_delta the
// final output_tokens, and neither carries a total.
func TestUsageTeeAnthropicStream(t *testing.T) {
	stream := strings.Join([]string{
		`event: message_start`,
		`data: {"type":"message_start","message":{"usage":{"input_tokens":727,"output_tokens":1}}}`,
		``,
		`event: content_block_delta`,
		`data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}`,
		``,
		`event: message_delta`,
		`data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":192}}`,
		``,
	}, "\n")

	res := &DispatchResult{UsageReady: make(chan struct{})}
	tee := newUsageTee(io.NopCloser(strings.NewReader(stream)), res, res.UsageReady)
	if _, err := io.ReadAll(tee); err != nil {
		t.Fatal(err)
	}
	tee.Close()
	deadline := time.After(2 * time.Second)
	select {
	case <-res.UsageReady:
	case <-deadline:
		t.Fatal("usage never finalized")
	}
	if res.Usage.PromptTokens != 727 || res.Usage.CompletionTokens != 192 {
		t.Fatalf("parts: %+v", res.Usage)
	}
	if res.Usage.TotalTokens != 919 {
		t.Fatalf("total = %d, want 919", res.Usage.TotalTokens)
	}
}
