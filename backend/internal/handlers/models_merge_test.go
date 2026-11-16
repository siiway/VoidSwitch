package handlers

import (
	"encoding/json"
	"testing"

	"github.com/siiway/voidswitch/internal/database"
)

// mergeJSON must recurse: the batch dialog offers a deep merge, and a nested
// block such as limit was previously replaced wholesale.
func TestMergeJSONIsDeep(t *testing.T) {
	base := database.JSON(`{"limit":{"context":1000,"output":10},"name":"a"}`)
	patch := database.JSON(`{"limit":{"context":2000},"name":"b"}`)

	var got map[string]any
	if err := json.Unmarshal(mergeJSON(base, patch), &got); err != nil {
		t.Fatalf("merge produced invalid JSON: %v", err)
	}
	if got["name"] != "b" {
		t.Fatalf("a top-level scalar should be replaced, got %v", got["name"])
	}
	limit, _ := got["limit"].(map[string]any)
	if limit["context"] != float64(2000) {
		t.Fatalf("the patched nested value should win, got %v", limit["context"])
	}
	if limit["output"] != float64(10) {
		t.Fatalf("an untouched nested value must survive, got %v", limit["output"])
	}
}

// A list replaces rather than concatenates, matching the documented contract.
func TestMergeJSONListsReplace(t *testing.T) {
	base := database.JSON(`{"input":["text","image"]}`)
	patch := database.JSON(`{"input":["text"]}`)
	var got map[string]any
	if err := json.Unmarshal(mergeJSON(base, patch), &got); err != nil {
		t.Fatalf("merge produced invalid JSON: %v", err)
	}
	list, _ := got["input"].([]any)
	if len(list) != 1 || list[0] != "text" {
		t.Fatalf("a list should be replaced, got %v", list)
	}
}

func TestMergeJSONEmptyBase(t *testing.T) {
	var got map[string]any
	if err := json.Unmarshal(mergeJSON(nil, database.JSON(`{"a":1}`)), &got); err != nil {
		t.Fatalf("merge produced invalid JSON: %v", err)
	}
	if got["a"] != float64(1) {
		t.Fatalf("merging onto an empty base should keep the patch, got %v", got)
	}
}
