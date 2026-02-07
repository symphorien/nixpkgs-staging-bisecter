{
  lib,
  python3,
  stdenv,
}:

stdenv.mkDerivation {
  name = "nixpkgs-staging-bisecter";

  src = ./.;

  buildInputs = [ python3 ];

  installPhase = ''
    mkdir -p $out/bin
    cp bisecter.py $out/bin/nixpkgs-staging-bisecter
  '';

  meta = {
    description = "minimize rebuilds when bisecting through mass rebuilds";
    homepage = "https://github.com/symphorien/nixpkgs-staging-bisecter";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "nixpkgs-staging-bisecter";
  };
}
