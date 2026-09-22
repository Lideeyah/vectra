"""Compare the deployed code against the artifact in this repo.

A raw byte comparison FAILS on this contract and that is expected: the router,
spender and USDC addresses are `immutable`, so the compiler writes them into the
deployed code at construction. The artifact records exactly where, in
`immutableReferences`. This masks those slots, compares everything else, and
then prints what was found in them so the constructor arguments are checked
rather than skipped.

Usage:  python3 tools/verify_bytecode.py [address] [rpc]
"""
import json, subprocess, sys

ADDR = sys.argv[1] if len(sys.argv) > 1 else "0x08Ed8562e2fD44C82EBA0CDfbC6F5Fdca3Cf19a0"
RPC = sys.argv[2] if len(sys.argv) > 2 else "https://rpc.xlayer.tech"
ART = "out/VectraMandate.sol/VectraMandate.json"

EXPECTED = {
    "router":  "7c5bee2a8091c3ef39072f64f18fac913060aeaf",
    "spender": "8b773d83bc66be128c60e07e17c8901f7a64f000",
    "usdc":    "b6ceceab302e2e4948951ee7843fc24e92933061",
}

r = subprocess.run(["cast", "code", ADDR, "--rpc-url", RPC],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"cast code failed: {r.stderr.strip()[:200]}")
on = bytes.fromhex(r.stdout.strip()[2:])

art = json.load(open(ART))["deployedBytecode"]
lo = bytes.fromhex(art["object"][2:])
refs = art.get("immutableReferences", {})

if len(on) != len(lo):
    sys.exit(f"LENGTH DIFFERS: chain {len(on)} vs artifact {len(lo)}")

found, masked = {}, 0
on_m, lo_m = bytearray(on), bytearray(lo)
for slots in refs.values():
    for s in slots:
        a, n = s["start"], s["length"]
        word = on[a:a + n].hex()
        found.setdefault(word[-40:], 0)
        found[word[-40:]] += 1
        on_m[a:a + n] = b"\0" * n
        lo_m[a:a + n] = b"\0" * n
        masked += n

print(f"address   {ADDR}")
print(f"artifact  {ART}")
print(f"length    {len(on)} bytes, {masked} of them immutable\n")

ok = bytes(on_m) == bytes(lo_m)
print("code outside immutables:",
      "EXACT MATCH" if ok else "DIFFERS  <-- the contract is not this source")

names = {v: k for k, v in EXPECTED.items()}
print("\nimmutable slots hold:")
bad = False
for word, count in found.items():
    nm = names.get(word)
    print(f"  0x{word}  x{count}  {nm or 'UNEXPECTED VALUE'}")
    if nm is None:
        bad = True

sys.exit(0 if (ok and not bad) else 1)
