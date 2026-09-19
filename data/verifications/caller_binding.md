# Caller binding

- ran: 2026-09-19T14:22:34Z
- address: 0xd24424Cc482D68b19e82aa7A6411C48aeD22215B
- fork block: latest
- exit: 0 (PASS)

```
    │   │   │   │   │   └─ ← [Return] 0x00000000000000000000000000000000000000000000000000000000004c4957ffffffffffffffffffffffffffffffffffffffffffffffffffb024bfcc627195
    │   │   │   │   ├─ [1143] 0x4ae46a509F6b1D9056937BA4500cb143933D2dc8::balanceOf(0xcc96b656b6dff0B5318d53271b82B7E7183b95D2) [staticcall]
    │   │   │   │   │   ├─ [745] 0x50607322Caa9CE5C27B8Cc403C476838CAAa9202::balanceOf(0xcc96b656b6dff0B5318d53271b82B7E7183b95D2) [delegatecall]
    │   │   │   │   │   │   └─ ← [Return] 0
    │   │   │   │   │   └─ ← [Return] 0
    │   │   │   │   └─ ← [Stop]
    │   │   │   ├─ [1791] 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5::balanceOf(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF) [staticcall]
    │   │   │   │   ├─ [906] 0x76C6851ea0B2741EeDcBBED240715E8817E85583::balanceOf(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF) [delegatecall]
    │   │   │   │   │   └─ ← [Return] 22477591950495339 [2.247e16]
    │   │   │   │   └─ ← [Return] 22477591950495339 [2.247e16]
    │   │   │   ├─ [36355] 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5::transfer(0x092B82D830F1DAbcefcc2B4A4226d17E76116477, 22477591950495339 [2.247e16])
    │   │   │   │   ├─ [35467] 0x76C6851ea0B2741EeDcBBED240715E8817E85583::transfer(0x092B82D830F1DAbcefcc2B4A4226d17E76116477, 22477591950495339 [2.247e16]) [delegatecall]
    │   │   │   │   │   ├─ [1826] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::sanctionsList() [staticcall]
    │   │   │   │   │   │   ├─ [944] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::sanctionsList() [delegatecall]
    │   │   │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000615dd3b9445a94334c1579f68115042d77cc7c44
    │   │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000615dd3b9445a94334c1579f68115042d77cc7c44
    │   │   │   │   │   ├─ [667] 0x615Dd3B9445A94334C1579F68115042D77CC7c44::isSanctioned(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF) [staticcall]
    │   │   │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
    │   │   │   │   │   ├─ [1826] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::sanctionsList() [staticcall]
    │   │   │   │   │   │   ├─ [944] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::sanctionsList() [delegatecall]
    │   │   │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000615dd3b9445a94334c1579f68115042d77cc7c44
    │   │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000615dd3b9445a94334c1579f68115042d77cc7c44
    │   │   │   │   │   ├─ [2667] 0x615Dd3B9445A94334C1579F68115042D77CC7c44::isSanctioned(0x092B82D830F1DAbcefcc2B4A4226d17E76116477) [staticcall]
    │   │   │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
    │   │   │   │   │   ├─ emit Transfer(from: 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, to: 0x092B82D830F1DAbcefcc2B4A4226d17E76116477, amount: 22477591950495339 [2.247e16])
    │   │   │   │   │   └─ ← [Return] true
    │   │   │   │   └─ ← [Return] true
    │   │   │   ├─ [56034] 0x092B82D830F1DAbcefcc2B4A4226d17E76116477::sellQuote(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5, 0x00)
    │   │   │   │   ├─ [1494] 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5::asset() [staticcall]
    │   │   │   │   │   ├─ [612] 0x76C6851ea0B2741EeDcBBED240715E8817E85583::asset() [delegatecall]
    │   │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000c845b2894dbddd03858fd2d643b4ef725fe0849d
    │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000c845b2894dbddd03858fd2d643b4ef725fe0849d
    │   │   │   │   ├─ [1791] 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5::balanceOf(0x092B82D830F1DAbcefcc2B4A4226d17E76116477) [staticcall]
    │   │   │   │   │   ├─ [906] 0x76C6851ea0B2741EeDcBBED240715E8817E85583::balanceOf(0x092B82D830F1DAbcefcc2B4A4226d17E76116477) [delegatecall]
    │   │   │   │   │   │   └─ ← [Return] 22477591950495339 [2.247e16]
    │   │   │   │   │   └─ ← [Return] 22477591950495339 [2.247e16]
    │   │   │   │   ├─ [45004] 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5::redeem(22477591950495339 [2.247e16], 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, 0x092B82D830F1DAbcefcc2B4A4226d17E76116477)
    │   │   │   │   │   ├─ [44110] 0x76C6851ea0B2741EeDcBBED240715E8817E85583::redeem(22477591950495339 [2.247e16], 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, 0x092B82D830F1DAbcefcc2B4A4226d17E76116477) [delegatecall]
    │   │   │   │   │   │   ├─ [2218] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::getCurrentMultiplier() [staticcall]
    │   │   │   │   │   │   │   ├─ [1330] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::getCurrentMultiplier() [delegatecall]
    │   │   │   │   │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000de6c1ee6669635000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000005
    │   │   │   │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000de6c1ee6669635000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000005
    │   │   │   │   │   │   ├─ [1826] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::sanctionsList() [staticcall]
    │   │   │   │   │   │   │   ├─ [944] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::sanctionsList() [delegatecall]
    │   │   │   │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000615dd3b9445a94334c1579f68115042d77cc7c44
    │   │   │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000615dd3b9445a94334c1579f68115042d77cc7c44
    │   │   │   │   │   │   ├─ [667] 0x615Dd3B9445A94334C1579F68115042D77CC7c44::isSanctioned(0x092B82D830F1DAbcefcc2B4A4226d17E76116477) [staticcall]
    │   │   │   │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
    │   │   │   │   │   │   ├─ emit Transfer(from: 0x092B82D830F1DAbcefcc2B4A4226d17E76116477, to: 0x0000000000000000000000000000000000000000, amount: 22477591950495339 [2.247e16])
    │   │   │   │   │   │   ├─ [23627] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::transfer(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, 22515830758017368 [2.251e16])
    │   │   │   │   │   │   │   ├─ [22739] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::transfer(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, 22515830758017368 [2.251e16]) [delegatecall]
    │   │   │   │   │   │   │   │   ├─ [2667] 0x615Dd3B9445A94334C1579F68115042D77CC7c44::isSanctioned(0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5) [staticcall]
    │   │   │   │   │   │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
    │   │   │   │   │   │   │   │   ├─ [667] 0x615Dd3B9445A94334C1579F68115042D77CC7c44::isSanctioned(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF) [staticcall]
    │   │   │   │   │   │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
    │   │   │   │   │   │   │   │   ├─ emit Transfer(from: 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5, to: 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, amount: 22515830758017368 [2.251e16])
    │   │   │   │   │   │   │   │   ├─ emit TransferShares(param0: 0xa8ddb5Cd96b5222AFe198316E9A57CAA642850D5, param1: 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, param2: 22477591950495338 [2.247e16])
    │   │   │   │   │   │   │   │   └─ ← [Return] true
    │   │   │   │   │   │   │   └─ ← [Return] true
    │   │   │   │   │   │   ├─ emit Withdraw(param0: 0x092B82D830F1DAbcefcc2B4A4226d17E76116477, param1: 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, param2: 0x092B82D830F1DAbcefcc2B4A4226d17E76116477, param3: 22515830758017368 [2.251e16], param4: 22477591950495339 [2.247e16])
    │   │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000000000000000000000000000004ffe075e278958
    │   │   │   │   │   └─ ← [Return] 0x000000000000000000000000000000000000000000000000004ffe075e278958
    │   │   │   │   ├─ [5214] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::balanceOf(0x092B82D830F1DAbcefcc2B4A4226d17E76116477) [staticcall]
    │   │   │   │   │   ├─ [4329] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::balanceOf(0x092B82D830F1DAbcefcc2B4A4226d17E76116477) [delegatecall]
    │   │   │   │   │   │   └─ ← [Return] 1
    │   │   │   │   │   └─ ← [Return] 1
    │   │   │   │   └─ ← [Stop]
    │   │   │   ├─ [3214] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::balanceOf(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF) [staticcall]
    │   │   │   │   ├─ [2329] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::balanceOf(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF) [delegatecall]
    │   │   │   │   │   └─ ← [Return] 22515830758017368 [2.251e16]
    │   │   │   │   └─ ← [Return] 22515830758017368 [2.251e16]
    │   │   │   ├─ [33927] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::transfer(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B, 22515830758017367 [2.251e16])
    │   │   │   │   ├─ [33039] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::transfer(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B, 22515830758017367 [2.251e16]) [delegatecall]
    │   │   │   │   │   ├─ [667] 0x615Dd3B9445A94334C1579F68115042D77CC7c44::isSanctioned(0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF) [staticcall]
    │   │   │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
    │   │   │   │   │   ├─ [2667] 0x615Dd3B9445A94334C1579F68115042D77CC7c44::isSanctioned(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [staticcall]
    │   │   │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
    │   │   │   │   │   ├─ emit Transfer(from: 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, to: 0xd24424Cc482D68b19e82aa7A6411C48aeD22215B, amount: 22515830758017367 [2.251e16])
    │   │   │   │   │   ├─ emit TransferShares(param0: 0x7c5bEE2a8091C3ef39072f64F18Fac913060AEaF, param1: 0xd24424Cc482D68b19e82aa7A6411C48aeD22215B, param2: 22477591950495337 [2.247e16])
    │   │   │   │   │   └─ ← [Return] true
    │   │   │   │   └─ ← [Return] true
    │   │   │   ├─ [3214] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [staticcall]
    │   │   │   │   ├─ [2329] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [delegatecall]
    │   │   │   │   │   └─ ← [Return] 22515830758017366 [2.251e16]
    │   │   │   │   └─ ← [Return] 22515830758017366 [2.251e16]
    │   │   │   ├─ emit OrderRecord(: 0xB6CEceAB302E2E4948951eE7843FC24E92933061, : 0xc845b2894dBddd03858fd2D643B4eF725fE0849d, : DefaultSender: [0x1804c8AB1F12E6bbf3894d4083f33e07309d1f38], : 5000000 [5e6], : 22515830758017366 [2.251e16])
    │   │   │   └─ ← [Return] 0x000000000000000000000000000000000000000000000000004ffe075e278956
    │   │   └─ ← [Return] 0x000000000000000000000000000000000000000000000000004ffe075e278956
    │   ├─ [3341] 0xB6CEceAB302E2E4948951eE7843FC24E92933061::approve(0x8b773D83bc66Be128c60e07E17C8901f7a64F000, 0)
    │   │   ├─ [2673] 0x908CB63Cded85Ee69525E2F95F7f38Da25aE0245::approve(0x8b773D83bc66Be128c60e07E17C8901f7a64F000, 0) [delegatecall]
    │   │   │   ├─ emit Approval(owner: 0xd24424Cc482D68b19e82aa7A6411C48aeD22215B, spender: 0x8b773D83bc66Be128c60e07E17C8901f7a64F000, amount: 0)
    │   │   │   └─ ← [Return] true
    │   │   └─ ← [Return] true
    │   ├─ [3214] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [staticcall]
    │   │   ├─ [2329] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [delegatecall]
    │   │   │   └─ ← [Return] 22515830758017366 [2.251e16]
    │   │   └─ ← [Return] 22515830758017366 [2.251e16]
    │   ├─ [33927] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::transfer(0x0000000000000000000000000000000000BEeF11, 22515830758017366 [2.251e16])
    │   │   ├─ [33039] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::transfer(0x0000000000000000000000000000000000BEeF11, 22515830758017366 [2.251e16]) [delegatecall]
    │   │   │   ├─ [667] 0x615Dd3B9445A94334C1579F68115042D77CC7c44::isSanctioned(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [staticcall]
    │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
    │   │   │   ├─ [2667] 0x615Dd3B9445A94334C1579F68115042D77CC7c44::isSanctioned(0x0000000000000000000000000000000000BEeF11) [staticcall]
    │   │   │   │   └─ ← [Return] 0x0000000000000000000000000000000000000000000000000000000000000000
    │   │   │   ├─ emit Transfer(from: 0xd24424Cc482D68b19e82aa7A6411C48aeD22215B, to: 0x0000000000000000000000000000000000BEeF11, amount: 22515830758017366 [2.251e16])
    │   │   │   ├─ emit TransferShares(param0: 0xd24424Cc482D68b19e82aa7A6411C48aeD22215B, param1: 0x0000000000000000000000000000000000BEeF11, param2: 22477591950495336 [2.247e16])
    │   │   │   └─ ← [Return] true
    │   │   └─ ← [Return] true
    │   ├─ [1250] 0xB6CEceAB302E2E4948951eE7843FC24E92933061::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [staticcall]
    │   │   ├─ [553] 0x908CB63Cded85Ee69525E2F95F7f38Da25aE0245::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [delegatecall]
    │   │   │   └─ ← [Return] 0
    │   │   └─ ← [Return] 0
    │   ├─ [1250] 0xB6CEceAB302E2E4948951eE7843FC24E92933061::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [staticcall]
    │   │   ├─ [553] 0x908CB63Cded85Ee69525E2F95F7f38Da25aE0245::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [delegatecall]
    │   │   │   └─ ← [Return] 0
    │   │   └─ ← [Return] 0
    │   ├─ [3214] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [staticcall]
    │   │   ├─ [2329] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [delegatecall]
    │   │   │   └─ ← [Return] 1
    │   │   └─ ← [Return] 1
    │   ├─ [2072] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::sharesOf(0x0000000000000000000000000000000000BEeF11) [staticcall]
    │   │   ├─ [1187] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::sharesOf(0x0000000000000000000000000000000000BEeF11) [delegatecall]
    │   │   │   └─ ← [Return] 22477591950495336 [2.247e16]
    │   │   └─ ← [Return] 22477591950495336 [2.247e16]
    │   ├─ emit Executed(id: 1, tokenIn: 0xB6CEceAB302E2E4948951eE7843FC24E92933061, tokenOut: 0xc845b2894dBddd03858fd2D643B4eF725fE0849d, amountIn: 5000000 [5e6], amountOut: 22515830758017366 [2.251e16], version: 1)
    │   └─ ← [Stop]
    ├─ [23714] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::balanceOf(0x0000000000000000000000000000000000BEeF11) [staticcall]
    │   ├─ [16329] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::balanceOf(0x0000000000000000000000000000000000BEeF11) [delegatecall]
    │   │   └─ ← [Return] 22515830758017365 [2.251e16]
    │   └─ ← [Return] 22515830758017365 [2.251e16]
    ├─ [0] console::log("NVDAx delivered to the mandate owner", 22515830758017365 [2.251e16]) [staticcall]
    │   └─ ← [Stop]
    ├─ [9750] 0xB6CEceAB302E2E4948951eE7843FC24E92933061::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [staticcall]
    │   ├─ [2553] 0x908CB63Cded85Ee69525E2F95F7f38Da25aE0245::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [delegatecall]
    │   │   └─ ← [Return] 0
    │   └─ ← [Return] 0
    ├─ [208] 0xd24424Cc482D68b19e82aa7A6411C48aeD22215B::DUST_WEI() [staticcall]
    │   └─ ← [Return] 1000
    ├─ [23714] 0xc845b2894dBddd03858fd2D643B4eF725fE0849d::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [staticcall]
    │   ├─ [16329] 0x65c40D624Af3B18C109fBF87B7DEff34CdC5f19b::balanceOf(0xd24424Cc482D68b19e82aa7A6411C48aeD22215B) [delegatecall]
    │   │   └─ ← [Return] 1
    │   └─ ← [Return] 1
    ├─ [208] 0xd24424Cc482D68b19e82aa7A6411C48aeD22215B::DUST_WEI() [staticcall]
    │   └─ ← [Return] 1000
    ├─ [0] console::log("CALLER BINDING: a payload built for the contract works when the contract forwards it") [staticcall]
    │   └─ ← [Stop]
    └─ ← [Stop]

Suite result: ok. 2 passed; 0 failed; 0 skipped; finished in 43.66s (78.99s CPU time)

Ran 1 test suite in 46.16s (43.66s CPU time): 2 tests passed, 0 failed, 0 skipped (2 total tests)
```
