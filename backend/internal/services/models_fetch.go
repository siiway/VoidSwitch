package services

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// FetchUpstreamModels calls a provider's models endpoint and extracts model ids.
// Used by the "fetch models from API" admin flow. It does NOT enforce public-IP
// restrictions in Phase 2 (documented as an SSRF hardening follow-up).
func FetchUpstreamModels(ctx context.Context, baseURL, method, path, token, keyRef string) ([]string, error) {
	if path == "" {
		path = "/models"
	}
	endpoint := path
	if !strings.HasPrefix(path, "http://") && !strings.HasPrefix(path, "https://") {
		endpoint = strings.TrimRight(baseURL, "/") + "/" + strings.TrimLeft(path, "/")
	}
	if _, err := url.Parse(endpoint); err != nil {
		return nil, fmt.Errorf("invalid url: %w", err)
	}
	if method == "" {
		method = http.MethodGet
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, nil)
	if err != nil {
		return nil, err
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	client := &http.Client{Timeout: 20 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("upstream returned %d", resp.StatusCode)
	}
	var parsed struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
		Models []struct {
			Name string `json:"name"`
			ID   string `json:"id"`
		} `json:"models"`
	}
	if err := json.Unmarshal(body, &parsed); err != nil {
		return nil, fmt.Errorf("parse models: %w", err)
	}
	seen := map[string]bool{}
	var out []string
	for _, d := range parsed.Data {
		if d.ID != "" && !seen[d.ID] {
			seen[d.ID] = true
			out = append(out, d.ID)
		}
	}
	for _, m := range parsed.Models {
		id := m.ID
		if id == "" {
			id = m.Name
		}
		if id != "" && !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out, nil
}

// ProbeProxy checks whether a proxy URL can reach a well-known endpoint.
func ProbeProxy(ctx context.Context, proxyURL string) (ok bool, status int, latencyMs float64, errStr string) {
	pu, err := url.Parse(proxyURL)
	if err != nil {
		return false, 0, 0, err.Error()
	}
	transport := &http.Transport{Proxy: http.ProxyURL(pu)}
	client := &http.Client{Transport: transport, Timeout: 10 * time.Second}
	start := time.Now()
	resp, err := client.Get("https://www.gstatic.com/generate_204")
	elapsed := float64(time.Since(start).Milliseconds())
	if err != nil {
		return false, 0, elapsed, err.Error()
	}
	defer resp.Body.Close()
	return resp.StatusCode < 400, resp.StatusCode, elapsed, ""
}
