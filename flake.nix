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
          itemSource = builtins.fromJSON (builtins.readFile ./sources/item.json);
          itemCsv = pkgs.fetchurl {
            url = "https://raw.githubusercontent.com/${itemSource.repository}/${itemSource.commit}/${itemSource.path}";
            sha256 = itemSource.sha256;
          };
          site = pkgs.stdenvNoCC.mkDerivation {
            pname = "icexiv-db";
            version = "0.1.0";
            src = pkgs.lib.fileset.toSource {
              root = ./.;
              fileset = pkgs.lib.fileset.unions [
                ./Notist.toml
                ./content
                ./templates
                ./static
                ./scripts
                ./sources
              ];
            };
            nativeBuildInputs = [
              notistPackage
              pkgs.python3
            ];
            buildPhase = ''
              runHook preBuild
              python3 scripts/items.py prepare --input ${itemCsv}
              mkdir -p inputs
              cp ${itemCsv} inputs/Item.csv
              notist build
              python3 scripts/check_site.py dist/icexiv-db
              runHook postBuild
            '';
            installPhase = ''
              runHook preInstall
              mkdir -p "$out"
              cp -r dist/icexiv-db/. "$out/"
              runHook postInstall
            '';
          };
        in
        {
          packages = {
            default = site;
            icexiv-db = site;
            notist = notistPackage;
          };
          checks.site = site;
          checks.data =
            pkgs.runCommand "icexiv-db-data-tests"
              {
                nativeBuildInputs = [ pkgs.python3 ];
                src = pkgs.lib.fileset.toSource {
                  root = ./.;
                  fileset = pkgs.lib.fileset.unions [
                    ./scripts
                    ./tests
                  ];
                };
              }
              ''
                cp -r "$src" source
                chmod -R u+w source
                cd source
                python3 -m unittest discover -s tests -v
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
              pkgs.python3
            ];
          };
        }
      );
}
