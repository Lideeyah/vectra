/**
 * Only the surface the interface uses. mandate() is read BY NAMED COMPONENT —
 * the tuple is a 10-tuple fixed at deployment (SPEC 5.2.2), and positional
 * reads are how an arity change becomes a silent failure.
 */
export const VECTRA_ABI = [
  {
    type: "function", name: "mandate", stateMutability: "view",
    inputs: [{ name: "id", type: "uint256" }],
    outputs: [
      { name: "owner_", type: "address" },
      { name: "agent", type: "address" },
      { name: "expiry", type: "uint64" },
      { name: "paused", type: "bool" },
      { name: "revoked", type: "bool" },
      { name: "driftBps", type: "uint16" },
      { name: "maxLegUsdc", type: "uint256" },
      { name: "totalCapUsdc", type: "uint256" },
      { name: "spentUsdc", type: "uint256" },
      { name: "version", type: "uint64" },
    ],
  },
  {
    type: "function", name: "position", stateMutability: "view",
    inputs: [{ name: "id", type: "uint256" }],
    outputs: [
      { name: "tokens", type: "address[]" },
      { name: "currentShares", type: "uint256[]" },
      { name: "targetShares", type: "uint256[]" },
    ],
  },
  {
    type: "function", name: "basket", stateMutability: "view",
    inputs: [{ name: "id", type: "uint256" }],
    outputs: [
      { name: "tokens", type: "address[]" },
      { name: "weightsBps", type: "uint16[]" },
      { name: "targetShares", type: "uint256[]" },
    ],
  },
  {
    type: "function", name: "isActive", stateMutability: "view",
    inputs: [{ name: "id", type: "uint256" }],
    outputs: [{ type: "bool" }],
  },
  {
    type: "function", name: "activeMandateOf", stateMutability: "view",
    inputs: [{ name: "", type: "address" }],
    outputs: [{ type: "uint256" }],
  },
  { type: "function", name: "router", stateMutability: "view", inputs: [], outputs: [{ type: "address" }] },
  { type: "function", name: "spender", stateMutability: "view", inputs: [], outputs: [{ type: "address" }] },
  { type: "function", name: "usdc", stateMutability: "view", inputs: [], outputs: [{ type: "address" }] },
  { type: "function", name: "DUST_WEI", stateMutability: "view", inputs: [], outputs: [{ type: "uint256" }] },
  { type: "function", name: "pause", stateMutability: "nonpayable", inputs: [{ name: "id", type: "uint256" }], outputs: [] },
  { type: "function", name: "resume", stateMutability: "nonpayable", inputs: [{ name: "id", type: "uint256" }], outputs: [] },
  { type: "function", name: "revoke", stateMutability: "nonpayable", inputs: [{ name: "id", type: "uint256" }], outputs: [] },
  {
    type: "event", name: "TargetsSet",
    inputs: [
      { name: "id", type: "uint256", indexed: true },
      { name: "previous", type: "uint256[]", indexed: false },
      { name: "current", type: "uint256[]", indexed: false },
      { name: "version", type: "uint64", indexed: false },
      { name: "timestamp", type: "uint256", indexed: false },
    ],
  },
  {
    type: "event", name: "Executed",
    inputs: [
      { name: "id", type: "uint256", indexed: true },
      { name: "tokenIn", type: "address", indexed: false },
      { name: "tokenOut", type: "address", indexed: false },
      { name: "amountIn", type: "uint256", indexed: false },
      { name: "amountOut", type: "uint256", indexed: false },
      { name: "version", type: "uint64", indexed: false },
    ],
  },
] as const;
