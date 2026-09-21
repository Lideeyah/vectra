import { createWalletClient, createPublicClient, defineChain, http, encodeAbiParameters, keccak256, getContractAddress } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { VECTRA_CREATION_BYTECODE } from "../lib/bytecode.generated";

const ROUTER = "0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF" as const;
const SPENDER = "0x8b773D83bc66Be128c60e07E17C8901f7a64F000" as const;
const USDC = "0xB6CEceAB302E2E4948951eE7843FC24E92933061" as const;
const EXPECTED = "0xc20f87eccd8af42fa47608d1c60b4cce916df43dce508670876ab6a8c6479db9";

const RPC = "http://127.0.0.1:8548";
const chain = defineChain({ id: 31337, name: "anvil", nativeCurrency: { name: "E", symbol: "E", decimals: 18 }, rpcUrls: { default: { http: [RPC] } } });
const pub = createPublicClient({ chain, transport: http(RPC) });
const account = privateKeyToAccount("0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80");
const wallet = createWalletClient({ account, chain, transport: http(RPC) });

// EXACTLY the construction the page performs.
const args = encodeAbiParameters(
  [{ type: "address" }, { type: "address" }, { type: "address" }],
  [ROUTER, SPENDER, USDC],
);
const data = (VECTRA_CREATION_BYTECODE + args.slice(2)) as `0x${string}`;

async function main() {
  const nonce = await pub.getTransactionCount({ address: account.address });
  const predicted = getContractAddress({ from: account.address, nonce: BigInt(nonce) });

  const hash = await wallet.sendTransaction({ data });
  const r = await pub.waitForTransactionReceipt({ hash });
  const addr = r.contractAddress!;
  const code = await pub.getBytecode({ address: addr });
  const h = keccak256(code!);

  console.log("predicted     ", predicted);
  console.log("actual        ", addr);
  console.log("address match ", predicted.toLowerCase() === addr.toLowerCase());
  console.log("runtime keccak", h);
  console.log("expected      ", EXPECTED);
  console.log(h === EXPECTED ? "HASH MATCHES — page construction is correct" : "HASH MISMATCH");
  process.exit(h === EXPECTED ? 0 : 1);
}
main();
