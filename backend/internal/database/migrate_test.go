package database

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/pressly/goose/v3"
)

// TestMigrationsParse guards the embedded migration set without a database: goose
// splits each file into Up/Down and rejects missing annotations, zero versions or
// duplicate versions. It catches the class of mistake that only shows up at
// startup (a malformed header, a re-used number), which no other test covers.
func TestMigrationsParse(t *testing.T) {
	if _, err := migrationFS.ReadDir("migrations"); err != nil {
		t.Fatalf("read embedded migrations: %v", err)
	}
	goose.SetBaseFS(migrationFS)
	migrations, err := goose.CollectMigrations("migrations", 0, 1<<62)
	if err != nil {
		t.Fatalf("goose rejected the migration set: %v", err)
	}
	if len(migrations) == 0 {
		t.Fatal("no migrations embedded")
	}
	seen := map[int64]string{}
	for _, m := range migrations {
		if prev, ok := seen[m.Version]; ok {
			t.Fatalf("duplicate migration version %d (%s and %s)", m.Version, prev, m.Source)
		}
		seen[m.Version] = m.Source
	}
}

// TestMigrationsApply runs the real migrations against a disposable PostgreSQL.
// It is skipped unless VOIDSWITCH_TEST_DATABASE_URL points at an empty database
// (scripts/dev-services.sh provisions one on 127.0.0.1:55432).
func TestMigrationsApply(t *testing.T) {
	url := strings.TrimSpace(os.Getenv("VOIDSWITCH_TEST_DATABASE_URL"))
	if url == "" {
		t.Skip("set VOIDSWITCH_TEST_DATABASE_URL to run the migration test")
	}
	ctx := context.Background()
	db, err := Open(url, false)
	if err != nil {
		t.Fatalf("open: %v", err)
	}
	defer db.Close()

	res, err := db.Migrate(ctx)
	if err != nil {
		t.Fatalf("migrate empty database: %v", err)
	}
	if res.Version == 0 {
		t.Fatal("migrations reported no applied version")
	}
	if res.Applied == 0 {
		t.Fatal("migrations applied nothing to an empty database")
	}

	// A second run must be a no-op: goose records what it applied, and 00006's
	// "DROP COLUMN IF EXISTS" is the reason re-running against a database that
	// never had the column cannot fail.
	if _, err := db.Migrate(ctx); err != nil {
		t.Fatalf("migrate again: %v", err)
	}

	// The tables the platform API depends on must exist.
	for _, table := range []string{"platform_api_keys", "audit_logs", "providers"} {
		var exists bool
		if err := db.Gorm.Raw(
			"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = ?)",
			table).Scan(&exists).Error; err != nil {
			t.Fatalf("check table %s: %v", table, err)
		}
		if !exists {
			t.Fatalf("table %s is missing after migration", table)
		}
	}
	var credential bool
	if err := db.Gorm.Raw(
		"SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'audit_logs' AND column_name = 'credential')").
		Scan(&credential).Error; err != nil {
		t.Fatalf("check audit_logs.credential: %v", err)
	}
	if !credential {
		t.Fatal("audit_logs.credential is missing after migration")
	}
}
