{
  description = "icexiv-db — data-driven FFXIV wiki built with Notist";

  inputs = {
    notist.url = "github:AzurIce/notist";
    # Share Notist's pinned build dependencies and Rust overlay.
    nixpkgs.follows = "notist/nixpkgs";
    crane.follows = "notist/crane";
    rust-overlay.follows = "notist/rust-overlay";
    flake-utils.follows = "notist/flake-utils";
  };

  outputs =
    {
      nixpkgs,
      crane,
      rust-overlay,
      flake-utils,
      notist,
      ...
    }:
    flake-utils.lib.eachSystem
      [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ]
      (
        system:
        let
          pkgs = import nixpkgs {
            inherit system;
            overlays = [ (import rust-overlay) ];
          };
          toolchain = pkgs.rust-bin.nightly."2026-10-01".default.override {
            extensions = [
              "rust-src"
              "rustfmt"
              "clippy"
              "rust-analyzer"
            ];
          };
          craneLib = (crane.mkLib pkgs).overrideToolchain toolchain;
          notistPackage = notist.packages.${system}.default;
          sitePython = pkgs.python3;
          mkSite =
            {
              gameExport,
              assetsSource ? "disabled",
            }:
            pkgs.stdenvNoCC.mkDerivation {
              pname = "icexiv-db";
              version = "0.1.0";
              src = pkgs.lib.fileset.toSource {
                root = ./.;
                fileset = pkgs.lib.fileset.unions [
                  ./Notist.toml
                  ./content
                  ./templates
                  ./static
                  ./modules
                  ./scripts
                  ./sources
                ];
              };
              nativeBuildInputs = [
                notistPackage
                sitePython
              ];
              buildPhase = ''
                runHook preBuild
                mkdir -p inputs
                cp -r ${gameExport} inputs/game-export
                python3 scripts/items.py prepare
                GAME_ASSETS_SOURCE=${pkgs.lib.escapeShellArg assetsSource} notist build
                python3 scripts/check_site.py notist-output/icexiv-db
                runHook postBuild
              '';
              installPhase = ''
                runHook preInstall
                mkdir -p "$out"
                cp -r notist-output/icexiv-db/. "$out/"
                runHook postInstall
              '';
            };
        in
        {
          packages = {
            notist = notistPackage;
            site-python = sitePython;
            # The released decoder lacks support for HCA in newer XIV SCDs.
            orchestrion-decoder = pkgs.vgmstream.overrideAttrs {
              version = "git-5d55744";
              src = pkgs.fetchzip {
                url = "https://codeload.github.com/vgmstream/vgmstream/tar.gz/5d5574405d61876cb995c17d86ccb8fd0be3565e";
                extension = "tar.gz";
                hash = "sha256-tBklGJfspNBf33I0AhZla+ac0EKxzhPARxZ9F/xSoxE=";
              };
            };
          };
          lib.mkSite = mkSite;
          checks.data =
            pkgs.runCommand "icexiv-db-data-tests"
              {
                nativeBuildInputs = [
                  sitePython
                  pkgs.nodejs
                ];
                src = pkgs.lib.fileset.toSource {
                  root = ./.;
                  fileset = pkgs.lib.fileset.unions [
                    ./scripts
                    ./tests
                    ./ops/cn
                    ./static/assets.js
                    ./static/catalog.js
                    ./static/item-list.js
                  ];
                };
              }
              ''
                cp -r "$src" source
                chmod -R u+w source
                cd source
                python3 -m unittest discover -s tests -v
                node --test tests/catalog.test.cjs
                touch "$out"
              '';
          formatter = pkgs.writeShellScriptBin "icexiv-db-fmt" ''
            if [ "$#" -eq 0 ]; then
              set -- flake.nix
            fi
            exec ${pkgs.nixfmt}/bin/nixfmt "$@"
          '';
          devShells.default = craneLib.devShell {
            packages = [
              notistPackage
              pkgs.git
              pkgs.just
              pkgs.miniserve
              sitePython
              pkgs.nodejs
            ];
          };
        }
      );
}
