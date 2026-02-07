{
  nixpkgs ? <nixpkgs>,
}:
let
  pkgs = import nixpkgs { };
in
rec {
  package = pkgs.callPackage ./package.nix { };
  devShell = pkgs.mkShell {
    packages = [
      package
    ];
  };
}
