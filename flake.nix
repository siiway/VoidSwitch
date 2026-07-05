{
  description = "VoidSwitch — production-grade multi-provider LLM API reverse proxy with proxy/key failover.";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        packages = {
          opencode-voidswitch =
            let
              pname = "opencode-voidswitch";
              version = "0.1.0";
            in
            pkgs.stdenv.mkDerivation {
              inherit pname version;
              src = ./opencode-plugin;

              # OpenCode consumes the plugin as TypeScript source (no build needed).
              # @opencode-ai/plugin is a peer dep resolved by OpenCode at runtime.
              dontBuild = true;

              installPhase = ''
                mkdir -p $out
                cp -r package.json tsconfig.json src/ $out/
              '';

              meta = {
                description = "Deep VoidSwitch integration for OpenCode";
                license = pkgs.lib.licenses.mit;
                maintainers = [ "RhenCloud <i@rhen.cloud>" ];
              };
            };
        };

        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            # Python backend (>=3.13)
            python3
            uv
            ruff
            basedpyright

            # Go backend
            go_1_26
            gopls
            golangci-lint

            # Frontend
            bun
            nodejs_24

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
      }
    );
}
