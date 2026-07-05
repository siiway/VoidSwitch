{
  description = "VoidSwitch — production-grade multi-provider LLM API reverse proxy with proxy/key failover.";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let pkgs = import nixpkgs { inherit system; };
      in {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            # Python backend (>=3.13)
            python3
            uv
            ruff
            basedpyright

            # Go backend
            go_1_25
            gopls
            golangci-lint

            # Frontend
            bun
            nodejs_22

            # Tools
            just
            watchexec
            nixfmt
            sqlite
          ];

          shellHook = ''
            export GOPATH="$HOME/go"
            export PATH="$GOPATH/bin:$PATH"
          '';
        };

        formatter = pkgs.nixfmt;
      });
}
