{
  nixpkgs ? <nixpkgs>,
}:
let
  pkgs = import nixpkgs { };
in
rec {
  nixpkgs-staging-bisecter = pkgs.callPackage ./package.nix { };
  package = nixpkgs-staging-bisecter;
  devShell = pkgs.mkShell {
    packages = [
      package
    ];
  };
}
