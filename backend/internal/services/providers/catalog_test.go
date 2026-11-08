package providers

import "testing"

func TestSubscriptionAdapters(t *testing.T) {
	cases := map[string]struct{ oauth, refresh, imp bool }{
		"codex":       {true, true, true},
		"grok-build":  {true, true, false},
		"claude-code": {true, true, true},
		"grok":        {false, false, true},
	}
	for typ, want := range cases {
		p := GetAdapter(newProviderForTest(typ))
		if p.CanOAuth() != want.oauth {
			t.Errorf("%s oauth=%v want %v", typ, p.CanOAuth(), want.oauth)
		}
		if p.CanRefresh() != want.refresh {
			t.Errorf("%s refresh=%v want %v", typ, p.CanRefresh(), want.refresh)
		}
		if p.CanImport() != want.imp {
			t.Errorf("%s import=%v want %v", typ, p.CanImport(), want.imp)
		}
	}
}
