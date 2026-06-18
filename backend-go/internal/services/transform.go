package services

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"
)

var anthropicToOpenAIStop = map[string]string{
	"end_turn":      "stop",
	"stop_sequence": "stop",
	"max_tokens":    "length",
	"tool_use":      "tool_calls",
}

var openAIToAnthropicFinish = map[string]string{
	"stop":           "end_turn",
	"length":         "max_tokens",
	"tool_calls":     "tool_use",
	"function_call":  "tool_use",
	"content_filter": "end_turn",
}

const DefaultMaxTokens = 4096
const thinkingSignature = "voidswitch"

type SSEvent struct {
	Event *string
	Data  string
}

func genID(prefix string) string {
	return fmt.Sprintf("%s-%x", prefix, time.Now().UnixMilli())
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func stringify(content any) string {
	if content == nil {
		return ""
	}
	switch v := content.(type) {
	case string:
		return v
	case []any:
		var out []string
		for _, part := range v {
			m, ok := part.(map[string]any)
			if !ok {
				out = append(out, fmt.Sprint(part))
				continue
			}
			if m["type"] == "text" {
				out = append(out, fmt.Sprint(m["text"]))
			}
		}
		return strings.Join(out, "")
	default:
		return fmt.Sprint(content)
	}
}

func safeJSON(value any) map[string]any {
	if m, ok := value.(map[string]any); ok {
		return m
	}
	s, ok := value.(string)
	if !ok || strings.TrimSpace(s) == "" {
		return map[string]any{}
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(s), &parsed); err == nil {
		return parsed
	}
	var generic any
	if err := json.Unmarshal([]byte(s), &generic); err == nil {
		if m, ok := generic.(map[string]any); ok {
			return m
		}
		return map[string]any{"value": generic}
	}
	return map[string]any{}
}

// ---------------------------------------------------------------------------
// Request: OpenAI -> Anthropic
// ---------------------------------------------------------------------------

func openAIContentToAnthropic(content any) any {
	if content == nil {
		return ""
	}
	if s, ok := content.(string); ok {
		return s
	}
	parts, ok := content.([]any)
	if !ok {
		return ""
	}
	var blocks []map[string]any
	for _, p := range parts {
		part, ok := p.(map[string]any)
		if !ok {
			continue
		}
		ptype, _ := part["type"].(string)
		if ptype == "text" {
			blocks = append(blocks, map[string]any{
				"type": "text",
				"text": part["text"],
			})
		} else if ptype == "image_url" {
			img, _ := part["image_url"].(map[string]any)
			var url string
			if img != nil {
				url, _ = img["url"].(string)
			}
			if strings.HasPrefix(url, "data:") && strings.Contains(url, ";base64,") {
				idx := strings.Index(url, ";base64,")
				mediaType := strings.TrimPrefix(url[:idx], "data:")
				b64 := url[idx+len(";base64,"):]
				if mediaType == "" {
					mediaType = "image/png"
				}
				blocks = append(blocks, map[string]any{
					"type": "image",
					"source": map[string]any{
						"type":       "base64",
						"media_type": mediaType,
						"data":       b64,
					},
				})
			} else if url != "" {
				blocks = append(blocks, map[string]any{
					"type":   "image",
					"source": map[string]any{"type": "url", "url": url},
				})
			}
		}
	}
	if len(blocks) == 0 {
		return ""
	}
	return blocks
}

func openAIToolToAnthropic(tool map[string]any) map[string]any {
	fn, _ := tool["function"].(map[string]any)
	if fn == nil {
		fn = tool
	}
	return map[string]any{
		"name":         fn["name"],
		"description":  fn["description"],
		"input_schema": defaultMap(fn["parameters"], map[string]any{"type": "object", "properties": map[string]any{}}),
	}
}

func openAIToolChoiceToAnthropic(choice any) map[string]any {
	switch v := choice.(type) {
	case string:
		switch v {
		case "auto":
			return map[string]any{"type": "auto"}
		case "required", "any":
			return map[string]any{"type": "any"}
		case "none":
			return map[string]any{"type": "auto"}
		default:
			return map[string]any{"type": "auto"}
		}
	case map[string]any:
		if v["type"] == "function" {
			fn, _ := v["function"].(map[string]any)
			name := ""
			if fn != nil {
				name, _ = fn["name"].(string)
			}
			return map[string]any{"type": "tool", "name": name}
		}
		return map[string]any{"type": "auto"}
	default:
		return map[string]any{"type": "auto"}
	}
}

func defaultMap(v any, def map[string]any) map[string]any {
	if m, ok := v.(map[string]any); ok {
		return m
	}
	return def
}

func OpenAIRequestToAnthropic(payload map[string]any) map[string]any {
	out := map[string]any{
		"model": payload["model"],
		"max_tokens": coalesceInt(
			toInt(payload["max_tokens"]),
			toInt(payload["max_completion_tokens"]),
			DefaultMaxTokens,
		),
	}
	var systemParts []string
	var messages []map[string]any

	for _, m := range toSlice(payload["messages"]) {
		msg, ok := m.(map[string]any)
		if !ok {
			continue
		}
		role, _ := msg["role"].(string)
		if role == "system" || role == "developer" {
			content := msg["content"]
			if s, ok := content.(string); ok {
				systemParts = append(systemParts, s)
			} else if arr, ok := content.([]any); ok {
				for _, p := range arr {
					if part, ok := p.(map[string]any); ok {
						systemParts = append(systemParts, fmt.Sprint(part["text"]))
					}
				}
			}
			continue
		}
		if role == "tool" {
			messages = append(messages, map[string]any{
				"role": "user",
				"content": []map[string]any{
					{
						"type":        "tool_result",
						"tool_use_id": msg["tool_call_id"],
						"content":     stringify(msg["content"]),
					},
				},
			})
			continue
		}
		if role == "assistant" && msg["tool_calls"] != nil {
			var blocks []map[string]any
			text := msg["content"]
			if s, ok := text.(string); ok && s != "" {
				blocks = append(blocks, map[string]any{"type": "text", "text": s})
			}
			for _, tc := range toSlice(msg["tool_calls"]) {
				call, _ := tc.(map[string]any)
				fn, _ := call["function"].(map[string]any)
				id, _ := call["id"].(string)
				if id == "" {
					id = genID("toolu")
				}
				name := ""
				var args any = ""
				if fn != nil {
					name, _ = fn["name"].(string)
					args = fn["arguments"]
				}
				blocks = append(blocks, map[string]any{
					"type":  "tool_use",
					"id":    id,
					"name":  name,
					"input": safeJSON(args),
				})
			}
			messages = append(messages, map[string]any{
				"role":    "assistant",
				"content": blocks,
			})
			continue
		}
		messages = append(messages, map[string]any{
			"role":    role,
			"content": openAIContentToAnthropic(msg["content"]),
		})
	}

	joined := strings.Join(systemParts, "\n\n")
	if joined != "" {
		out["system"] = joined
	}
	out["messages"] = messages

	for _, src := range []string{"temperature", "top_p"} {
		if v, ok := payload[src]; ok && v != nil {
			out[src] = v
		}
	}

	if stop, ok := payload["stop"]; ok && stop != nil {
		if s, ok := stop.(string); ok {
			out["stop_sequences"] = []string{s}
		} else {
			out["stop_sequences"] = stop
		}
	}

	if v, ok := payload["stream"]; ok && v != nil {
		if stream, ok := v.(bool); ok && stream {
			out["stream"] = true
		}
	}

	if tools := toSlice(payload["tools"]); len(tools) > 0 {
		var anthropicTools []map[string]any
		for _, t := range tools {
			if tm, ok := t.(map[string]any); ok {
				anthropicTools = append(anthropicTools, openAIToolToAnthropic(tm))
			}
		}
		out["tools"] = anthropicTools
	}

	if tc, ok := payload["tool_choice"]; ok && tc != nil {
		out["tool_choice"] = openAIToolChoiceToAnthropic(tc)
	}

	return out
}

// ---------------------------------------------------------------------------
// Request: Anthropic -> OpenAI
// ---------------------------------------------------------------------------

func collapseOpenAIContent(parts []map[string]any) any {
	if len(parts) == 0 {
		return ""
	}
	if len(parts) == 1 && parts[0]["type"] == "text" {
		return parts[0]["text"]
	}
	allText := true
	for _, p := range parts {
		if p["type"] != "text" {
			allText = false
			break
		}
	}
	if allText {
		var sb strings.Builder
		for _, p := range parts {
			sb.WriteString(fmt.Sprint(p["text"]))
		}
		return sb.String()
	}
	return parts
}

func anthropicToolToOpenAI(tool map[string]any) map[string]any {
	return map[string]any{
		"type": "function",
		"function": map[string]any{
			"name":        tool["name"],
			"description": tool["description"],
			"parameters":  defaultMap(tool["input_schema"], map[string]any{"type": "object", "properties": map[string]any{}}),
		},
	}
}

func anthropicToolChoiceToOpenAI(choice any) any {
	m, ok := choice.(map[string]any)
	if !ok {
		return "auto"
	}
	ctype, _ := m["type"].(string)
	switch ctype {
	case "auto":
		return "auto"
	case "any":
		return "required"
	case "tool":
		name, _ := m["name"].(string)
		return map[string]any{
			"type":     "function",
			"function": map[string]any{"name": name},
		}
	default:
		return "auto"
	}
}

func AnthropicRequestToOpenAI(payload map[string]any) map[string]any {
	var messages []map[string]any

	system := payload["system"]
	if s, ok := system.(string); ok && s != "" {
		messages = append(messages, map[string]any{"role": "system", "content": s})
	} else if arr, ok := system.([]any); ok {
		var parts []string
		for _, p := range arr {
			if pm, ok := p.(map[string]any); ok {
				parts = append(parts, fmt.Sprint(pm["text"]))
			}
		}
		text := strings.Join(parts, "\n\n")
		if text != "" {
			messages = append(messages, map[string]any{"role": "system", "content": text})
		}
	}

	for _, m := range toSlice(payload["messages"]) {
		msg, ok := m.(map[string]any)
		if !ok {
			continue
		}
		role, _ := msg["role"].(string)
		content := msg["content"]

		if s, ok := content.(string); ok {
			messages = append(messages, map[string]any{"role": role, "content": s})
			continue
		}

		blocks, ok := content.([]any)
		if !ok {
			continue
		}

		var toolCalls []map[string]any
		var textParts []map[string]any
		var toolResults []map[string]any
		var reasoningParts []string

		for _, b := range blocks {
			block, ok := b.(map[string]any)
			if !ok {
				continue
			}
			btype, _ := block["type"].(string)
			switch btype {
			case "text":
				textParts = append(textParts, map[string]any{"type": "text", "text": block["text"]})
			case "thinking", "redacted_thinking":
				thinkingText := fmt.Sprint(block["thinking"])
				if thinkingText != "<nil>" && thinkingText != "" {
					reasoningParts = append(reasoningParts, thinkingText)
				}
			case "image":
				src, _ := block["source"].(map[string]any)
				var dataURL string
				if src != nil && fmt.Sprint(src["type"]) == "base64" {
					media := fmt.Sprint(src["media_type"])
					if media == "<nil>" || media == "" {
						media = "image/png"
					}
					dataURL = fmt.Sprintf("data:%s;base64,%s", media, src["data"])
				} else if src != nil {
					dataURL = fmt.Sprint(src["url"])
				}
				textParts = append(textParts, map[string]any{
					"type":      "image_url",
					"image_url": map[string]any{"url": dataURL},
				})
			case "tool_use":
				id, _ := block["id"].(string)
				if id == "" {
					id = genID("call")
				}
				name, _ := block["name"].(string)
				input := block["input"]
				args, _ := json.Marshal(input)
				toolCalls = append(toolCalls, map[string]any{
					"id":   id,
					"type": "function",
					"function": map[string]any{
						"name":      name,
						"arguments": string(args),
					},
				})
			case "tool_result":
				toolResults = append(toolResults, map[string]any{
					"role":         "tool",
					"tool_call_id": block["tool_use_id"],
					"content":      stringify(block["content"]),
				})
			}
		}

		reasoningText := strings.Join(reasoningParts, "")
		if role == "assistant" && len(toolCalls) > 0 {
			text := ""
			for _, p := range textParts {
				if p["type"] == "text" {
					text += fmt.Sprint(p["text"])
				}
			}
			var contentVal any
			if text != "" {
				contentVal = text
			}
			assistantMsg := map[string]any{
				"role":       "assistant",
				"content":    contentVal,
				"tool_calls": toolCalls,
			}
			if reasoningText != "" {
				assistantMsg["reasoning_content"] = reasoningText
			}
			messages = append(messages, assistantMsg)
		} else if len(toolResults) > 0 {
			messages = append(messages, toolResults...)
			leftover := textParts
			hasText := false
			for _, p := range leftover {
				if p["type"] == "text" && fmt.Sprint(p["text"]) != "" && fmt.Sprint(p["text"]) != "<nil>" {
					hasText = true
					break
				}
			}
			if len(leftover) > 0 && hasText {
				messages = append(messages, map[string]any{"role": role, "content": leftover})
			}
		} else {
			simple := collapseOpenAIContent(textParts)
			simpleMsg := map[string]any{
				"role":    role,
				"content": simple,
			}
			if role == "assistant" && reasoningText != "" {
				simpleMsg["reasoning_content"] = reasoningText
			}
			messages = append(messages, simpleMsg)
		}
	}

	out := map[string]any{
		"model":    payload["model"],
		"messages": messages,
	}

	if v := toInt(payload["max_tokens"]); v != 0 {
		out["max_tokens"] = v
	}

	for _, key := range []string{"temperature", "top_p"} {
		if v, ok := payload[key]; ok && v != nil {
			out[key] = v
		}
	}

	if seqs, ok := payload["stop_sequences"]; ok && seqs != nil {
		out["stop"] = seqs
	}

	if v, ok := payload["stream"]; ok && v != nil {
		if stream, ok := v.(bool); ok && stream {
			out["stream"] = true
		}
	}

	if tools := toSlice(payload["tools"]); len(tools) > 0 {
		var openAITools []map[string]any
		for _, t := range tools {
			if tm, ok := t.(map[string]any); ok {
				openAITools = append(openAITools, anthropicToolToOpenAI(tm))
			}
		}
		out["tools"] = openAITools
	}

	if tc, ok := payload["tool_choice"]; ok && tc != nil {
		out["tool_choice"] = anthropicToolChoiceToOpenAI(tc)
	}

	return out
}

// ---------------------------------------------------------------------------
// Non-streaming responses
// ---------------------------------------------------------------------------

func AnthropicResponseToOpenAI(resp map[string]any, model string) map[string]any {
	var contentText string
	var reasoningText string
	var toolCalls []map[string]any

	for _, block := range toSlice(resp["content"]) {
		b, ok := block.(map[string]any)
		if !ok {
			continue
		}
		btype, _ := b["type"].(string)
		switch btype {
		case "text":
			contentText += fmt.Sprint(b["text"])
		case "thinking":
			reasoningText += fmt.Sprint(b["thinking"])
		case "tool_use":
			id, _ := b["id"].(string)
			if id == "" {
				id = genID("call")
			}
			name, _ := b["name"].(string)
			input := b["input"]
			args, _ := json.Marshal(input)
			toolCalls = append(toolCalls, map[string]any{
				"id":   id,
				"type": "function",
				"function": map[string]any{
					"name":      name,
					"arguments": string(args),
				},
			})
		}
	}

	var contentVal any
	if contentText != "" {
		contentVal = contentText
	}
	message := map[string]any{
		"role":    "assistant",
		"content": contentVal,
	}
	if reasoningText != "" {
		message["reasoning_content"] = reasoningText
	}
	if len(toolCalls) > 0 {
		message["tool_calls"] = toolCalls
	}

	usage, _ := resp["usage"].(map[string]any)
	inputTokens := toInt(usage["input_tokens"])
	outputTokens := toInt(usage["output_tokens"])

	id, _ := resp["id"].(string)
	if id == "" {
		id = genID("chatcmpl")
	}
	rmodel, _ := resp["model"].(string)
	if rmodel == "" {
		rmodel = model
	}

	stopReason, _ := resp["stop_reason"].(string)
	finishReason := anthropicToOpenAIStop[stopReason]
	if finishReason == "" {
		finishReason = "stop"
	}

	return map[string]any{
		"id":      id,
		"object":  "chat.completion",
		"created": int(time.Now().Unix()),
		"model":   rmodel,
		"choices": []map[string]any{
			{
				"index":   0,
				"message": message,
				"finish_reason": finishReason,
			},
		},
		"usage": map[string]any{
			"prompt_tokens":     inputTokens,
			"completion_tokens": outputTokens,
			"total_tokens":      inputTokens + outputTokens,
		},
	}
}

func OpenAIResponseToAnthropic(resp map[string]any, model string) map[string]any {
	choices := toSlice(resp["choices"])
	var choice map[string]any
	if len(choices) > 0 {
		choice, _ = choices[0].(map[string]any)
	}
	if choice == nil {
		choice = map[string]any{}
	}
	message, _ := choice["message"].(map[string]any)
	if message == nil {
		message = map[string]any{}
	}
	var blocks []map[string]any
	reasoning, _ := message["reasoning_content"].(string)
	if reasoning != "" {
		blocks = append(blocks, map[string]any{
			"type":      "thinking",
			"thinking":  reasoning,
			"signature": thinkingSignature,
		})
	}
	text := message["content"]
	if s, ok := text.(string); ok && s != "" {
		blocks = append(blocks, map[string]any{"type": "text", "text": s})
	} else if arr, ok := text.([]any); ok {
		for _, p := range arr {
			if pm, ok := p.(map[string]any); ok && pm["type"] == "text" {
				blocks = append(blocks, map[string]any{"type": "text", "text": pm["text"]})
			}
		}
	}
	for _, tc := range toSlice(message["tool_calls"]) {
		call, _ := tc.(map[string]any)
		fn, _ := call["function"].(map[string]any)
		id, _ := call["id"].(string)
		if id == "" {
			id = genID("toolu")
		}
		name := ""
		var args any = ""
		if fn != nil {
			name, _ = fn["name"].(string)
			args = fn["arguments"]
		}
		blocks = append(blocks, map[string]any{
			"type":  "tool_use",
			"id":    id,
			"name":  name,
			"input": safeJSON(args),
		})
	}

	usage, _ := resp["usage"].(map[string]any)

	id, _ := resp["id"].(string)
	if id == "" {
		id = genID("msg")
	}
	rmodel, _ := resp["model"].(string)
	if rmodel == "" {
		rmodel = model
	}

	finishReason, _ := choice["finish_reason"].(string)
	if finishReason == "" {
		finishReason = "stop"
	}
	stopReason := openAIToAnthropicFinish[finishReason]
	if stopReason == "" {
		stopReason = "end_turn"
	}

	if len(blocks) == 0 {
		blocks = []map[string]any{{"type": "text", "text": ""}}
	}

	return map[string]any{
		"id":      id,
		"type":    "message",
		"role":    "assistant",
		"model":   rmodel,
		"content": blocks,
		"stop_reason":   stopReason,
		"stop_sequence": nil,
		"usage": map[string]any{
			"input_tokens":  toInt(usage["prompt_tokens"]),
			"output_tokens": toInt(usage["completion_tokens"]),
		},
	}
}

// ---------------------------------------------------------------------------
// SSE parsing
// ---------------------------------------------------------------------------

func IterSSE(stream <-chan []byte) <-chan SSEvent {
	out := make(chan SSEvent)
	go func() {
		defer close(out)
		var buffer string
		for chunk := range stream {
			buffer += string(chunk)
			for {
				idx := strings.Index(buffer, "\n\n")
				if idx == -1 {
					break
				}
				raw := buffer[:idx]
				buffer = buffer[idx+2:]
				var event *string
				var dataLines []string
				for _, line := range strings.Split(raw, "\n") {
					if strings.HasPrefix(line, "event:") {
						val := strings.TrimSpace(line[6:])
						event = &val
					} else if strings.HasPrefix(line, "data:") {
						dataLines = append(dataLines, strings.TrimPrefix(line[5:], " "))
					}
				}
				if len(dataLines) > 0 {
					out <- SSEvent{Event: event, Data: strings.Join(dataLines, "\n")}
				}
			}
		}
	}()
	return out
}

func sse(event string, data any) []byte {
	bytes, _ := json.Marshal(data)
	return []byte(fmt.Sprintf("event: %s\ndata: %s\n\n", event, string(bytes)))
}

func dataSSE(data any) []byte {
	if s, ok := data.(string); ok {
		return []byte(fmt.Sprintf("data: %s\n\n", s))
	}
	bytes, _ := json.Marshal(data)
	return []byte(fmt.Sprintf("data: %s\n\n", string(bytes)))
}

// ---------------------------------------------------------------------------
// Streaming: Anthropic upstream -> OpenAI client
// ---------------------------------------------------------------------------

func AnthropicStreamToOpenAI(stream <-chan []byte, model string) <-chan []byte {
	out := make(chan []byte)
	go func() {
		defer close(out)
		completionID := genID("chatcmpl")
		created := int(time.Now().Unix())
		base := map[string]any{
			"id":      completionID,
			"object":  "chat.completion.chunk",
			"created": created,
			"model":   model,
		}
		started := false
		blockTypes := map[int]string{}
		toolIndexes := map[int]int{}
		nextToolIndex := 0

		for evt := range IterSSE(stream) {
			if evt.Data == "" || evt.Data == "[DONE]" {
				continue
			}
			var payload map[string]any
			if err := json.Unmarshal([]byte(evt.Data), &payload); err != nil {
				continue
			}

			etype := ""
			if evt.Event != nil {
				etype = *evt.Event
			}
			if etype == "" {
				etype, _ = payload["type"].(string)
			}

			switch etype {
			case "message_start":
				started = true
				out <- dataSSE(mergeMaps(base, map[string]any{
					"choices": []map[string]any{
						{"index": 0, "delta": map[string]any{"role": "assistant"}, "finish_reason": nil},
					},
				}))
			case "content_block_start":
				idx := toInt(payload["index"])
				block, _ := payload["content_block"].(map[string]any)
				if block != nil {
					blockTypes[idx], _ = block["type"].(string)
				}
				if blockTypes[idx] == "tool_use" {
					toolIndexes[idx] = nextToolIndex
					bid, _ := block["id"].(string)
					bname, _ := block["name"].(string)
					out <- dataSSE(mergeMaps(base, map[string]any{
						"choices": []map[string]any{
							{
								"index": 0,
								"delta": map[string]any{
									"tool_calls": []map[string]any{
										{
											"index": nextToolIndex,
											"id":    bid,
											"type":  "function",
											"function": map[string]any{
												"name":      bname,
												"arguments": "",
											},
										},
									},
								},
								"finish_reason": nil,
							},
						},
					}))
					nextToolIndex++
				}
			case "content_block_delta":
				idx := toInt(payload["index"])
				delta, _ := payload["delta"].(map[string]any)
				if delta == nil {
					continue
				}
				dtype, _ := delta["type"].(string)
				if dtype == "text_delta" {
					out <- dataSSE(mergeMaps(base, map[string]any{
						"choices": []map[string]any{
							{
								"index": 0,
								"delta": map[string]any{
									"content": delta["text"],
								},
								"finish_reason": nil,
							},
						},
					}))
				} else if dtype == "thinking_delta" {
					out <- dataSSE(mergeMaps(base, map[string]any{
						"choices": []map[string]any{
							{
								"index": 0,
								"delta": map[string]any{
									"reasoning_content": delta["thinking"],
								},
								"finish_reason": nil,
							},
						},
					}))
				} else if dtype == "input_json_delta" {
					tidx := toolIndexes[idx]
					out <- dataSSE(mergeMaps(base, map[string]any{
						"choices": []map[string]any{
							{
								"index": 0,
								"delta": map[string]any{
									"tool_calls": []map[string]any{
										{
											"index": tidx,
											"function": map[string]any{
												"arguments": delta["partial_json"],
											},
										},
									},
								},
								"finish_reason": nil,
							},
						},
					}))
				}
			case "message_delta":
				mdelta, _ := payload["delta"].(map[string]any)
				stop := ""
				if mdelta != nil {
					stop, _ = mdelta["stop_reason"].(string)
				}
				finish := anthropicToOpenAIStop[stop]
				if finish == "" {
					finish = "stop"
				}
				chunk := mergeMaps(base, map[string]any{
					"choices": []map[string]any{
						{"index": 0, "delta": map[string]any{}, "finish_reason": finish},
					},
				})
				if u, _ := payload["usage"].(map[string]any); u != nil {
					it := toInt(u["input_tokens"])
					ot := toInt(u["output_tokens"])
					chunk["usage"] = map[string]any{
						"prompt_tokens":     it,
						"completion_tokens": ot,
						"total_tokens":      it + ot,
					}
				}
				out <- dataSSE(chunk)
			case "message_stop":
				goto done
			}
		}

		if !started {
			out <- dataSSE(mergeMaps(base, map[string]any{
				"choices": []map[string]any{
					{
						"index": 0,
						"delta": map[string]any{"role": "assistant", "content": ""},
						"finish_reason": "stop",
					},
				},
			}))
		}
	done:
		out <- []byte("data: [DONE]\n\n")
	}()
	return out
}

// ---------------------------------------------------------------------------
// Streaming: OpenAI upstream -> Anthropic client
// ---------------------------------------------------------------------------

func OpenAIStreamToAnthropic(stream <-chan []byte, model string) <-chan []byte {
	out := make(chan []byte)
	go func() {
		defer close(out)
		msgID := genID("msg")
		out <- sse("message_start", map[string]any{
			"type": "message_start",
			"message": map[string]any{
				"id":           msgID,
				"type":         "message",
				"role":         "assistant",
				"model":        model,
				"content":      []any{},
				"stop_reason":  nil,
				"stop_sequence": nil,
				"usage":        map[string]any{"input_tokens": 0, "output_tokens": 0},
			},
		})
		out <- sse("ping", map[string]any{"type": "ping"})

		textBlockOpen := false
		textIndex := 0
		thinkingBlockOpen := false
		thinkingIndex := 0
		toolBlocks := map[int]int{}
		nextBlock := 0
		finishReason := "stop"
		usageOut := map[string]int{"input_tokens": 0, "output_tokens": 0}

		closeThinking := func() {
			out <- sse("content_block_delta", map[string]any{
				"type":  "content_block_delta",
				"index": thinkingIndex,
				"delta": map[string]any{
					"type":      "signature_delta",
					"signature": thinkingSignature,
				},
			})
			out <- sse("content_block_stop", map[string]any{
				"type":  "content_block_stop",
				"index": thinkingIndex,
			})
		}

		for evt := range IterSSE(stream) {
			if evt.Data == "[DONE]" {
				break
			}
			var chunk map[string]any
			if err := json.Unmarshal([]byte(evt.Data), &chunk); err != nil {
				continue
			}
			if u, ok := chunk["usage"].(map[string]any); ok {
				usageOut["input_tokens"] = toInt(u["prompt_tokens"])
				usageOut["output_tokens"] = toInt(u["completion_tokens"])
			}
			choices := toSlice(chunk["choices"])
			var choice map[string]any
			if len(choices) > 0 {
				choice, _ = choices[0].(map[string]any)
			}
			if choice == nil {
				choice = map[string]any{}
			}
			delta, _ := choice["delta"].(map[string]any)
			if delta == nil {
				delta = map[string]any{}
			}
			reasoning, _ := delta["reasoning_content"].(string)

			if reasoning != "" {
				if !thinkingBlockOpen && !textBlockOpen && len(toolBlocks) == 0 {
					out <- sse("content_block_start", map[string]any{
						"type":  "content_block_start",
						"index": nextBlock,
						"content_block": map[string]any{
							"type":     "thinking",
							"thinking": "",
						},
					})
					thinkingBlockOpen = true
					thinkingIndex = nextBlock
					nextBlock++
				}
				if thinkingBlockOpen {
					out <- sse("content_block_delta", map[string]any{
						"type":  "content_block_delta",
						"index": thinkingIndex,
						"delta": map[string]any{
							"type":     "thinking_delta",
							"thinking": reasoning,
						},
					})
				}
			}

			if content, ok := delta["content"]; ok && content != nil && fmt.Sprint(content) != "" {
				if thinkingBlockOpen {
					closeThinking()
					thinkingBlockOpen = false
				}
				if !textBlockOpen {
					out <- sse("content_block_start", map[string]any{
						"type":  "content_block_start",
						"index": nextBlock,
						"content_block": map[string]any{
							"type": "text",
							"text": "",
						},
					})
					textBlockOpen = true
					textIndex = nextBlock
					nextBlock++
				}
				out <- sse("content_block_delta", map[string]any{
					"type":  "content_block_delta",
					"index": textIndex,
					"delta": map[string]any{
						"type": "text_delta",
						"text": fmt.Sprint(content),
					},
				})
			}

			for _, tc := range toSlice(delta["tool_calls"]) {
				call, _ := tc.(map[string]any)
				oaiIdx := toInt(call["index"])
				if _, exists := toolBlocks[oaiIdx]; !exists {
					if thinkingBlockOpen {
						closeThinking()
						thinkingBlockOpen = false
					}
					if textBlockOpen {
						out <- sse("content_block_stop", map[string]any{
							"type":  "content_block_stop",
							"index": textIndex,
						})
						textBlockOpen = false
					}
					toolBlocks[oaiIdx] = nextBlock
					fn, _ := call["function"].(map[string]any)
					callID, _ := call["id"].(string)
					if callID == "" {
						callID = genID("toolu")
					}
					name := ""
					if fn != nil {
						name, _ = fn["name"].(string)
					}
					out <- sse("content_block_start", map[string]any{
						"type":  "content_block_start",
						"index": nextBlock,
						"content_block": map[string]any{
							"type":  "tool_use",
							"id":    callID,
							"name":  name,
							"input": map[string]any{},
						},
					})
					nextBlock++
				}
				fn, _ := call["function"].(map[string]any)
				args := ""
				if fn != nil {
					args, _ = fn["arguments"].(string)
				}
				if args != "" {
					out <- sse("content_block_delta", map[string]any{
						"type":  "content_block_delta",
						"index": toolBlocks[oaiIdx],
						"delta": map[string]any{
							"type":         "input_json_delta",
							"partial_json": args,
						},
					})
				}
			}

			if fr, ok := choice["finish_reason"]; ok && fr != nil {
				frStr, _ := fr.(string)
				if frStr != "" {
					finishReason = openAIToAnthropicFinish[frStr]
					if finishReason == "" {
						finishReason = "end_turn"
					}
				}
			}
		}

		if thinkingBlockOpen {
			closeThinking()
		}
		if textBlockOpen {
			out <- sse("content_block_stop", map[string]any{
				"type":  "content_block_stop",
				"index": textIndex,
			})
		}
		for _, blockIndex := range toolBlocks {
			out <- sse("content_block_stop", map[string]any{
				"type":  "content_block_stop",
				"index": blockIndex,
			})
		}
		out <- sse("message_delta", map[string]any{
			"type": "message_delta",
			"delta": map[string]any{
				"stop_reason":   finishReason,
				"stop_sequence": nil,
			},
			"usage": map[string]any{
				"input_tokens":  usageOut["input_tokens"],
				"output_tokens": usageOut["output_tokens"],
			},
		})
		out <- sse("message_stop", map[string]any{"type": "message_stop"})
	}()
	return out
}

// ---------------------------------------------------------------------------
// Shared utilities
// ---------------------------------------------------------------------------

func toSlice(v any) []any {
	switch val := v.(type) {
	case []any:
		return val
	case nil:
		return nil
	default:
		return nil
	}
}

func toInt(v any) int {
	switch val := v.(type) {
	case float64:
		return int(val)
	case int:
		return val
	case json.Number:
		n, _ := val.Int64()
		return int(n)
	case string:
		n, _ := strconv.Atoi(val)
		return n
	default:
		return 0
	}
}

func coalesceInt(vals ...int) int {
	for _, v := range vals {
		if v != 0 {
			return v
		}
	}
	return 0
}

func mergeMaps(base, extra map[string]any) map[string]any {
	result := make(map[string]any, len(base)+len(extra))
	for k, v := range base {
		result[k] = v
	}
	for k, v := range extra {
		result[k] = v
	}
	return result
}
