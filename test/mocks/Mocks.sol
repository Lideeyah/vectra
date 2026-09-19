// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";

/// @notice Plain non-rebasing token. Stands in for USDC.
contract MockUSDC {
    string public name = "USD Coin";
    string public symbol = "USDC";
    uint8 public decimals = 6;
    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply += amount;
    }

    function approve(address s, uint256 a) external returns (bool) {
        allowance[msg.sender][s] = a;
        return true;
    }

    function transfer(address to, uint256 a) external returns (bool) {
        balanceOf[msg.sender] -= a;
        balanceOf[to] += a;
        return true;
    }

    function transferFrom(address f, address t, uint256 a) external returns (bool) {
        uint256 al = allowance[f][msg.sender];
        if (al != type(uint256).max) allowance[f][msg.sender] = al - a;
        balanceOf[f] -= a;
        balanceOf[t] += a;
        return true;
    }
}

/**
 * @notice Rebasing token modelled on xStocks as deployed on X Layer.
 *
 * Shares are the stored quantity and never change on a corporate event.
 * balanceOf() is derived: shares * multiplier / 1e18. Raising the multiplier
 * therefore changes every holder's balance with no transfer occurring, which is
 * exactly the condition that breaks "after = before - sent".
 *
 * CRWDx is live at multiplier 4.0, so this is modelled behaviour, not invented.
 */
contract MockRebasingToken {
    string public name;
    string public symbol;
    uint8 public decimals = 18;

    uint256 public multiplier = 1e18;
    uint256 public totalShares;
    mapping(address => uint256) private _shares;
    mapping(address => mapping(address => uint256)) public allowance;

    constructor(string memory n, string memory s) {
        name = n;
        symbol = s;
    }

    function sharesOf(address a) external view returns (uint256) {
        return _shares[a];
    }

    function balanceOf(address a) public view returns (uint256) {
        return (_shares[a] * multiplier) / 1e18;
    }

    function totalSupply() external view returns (uint256) {
        return (totalShares * multiplier) / 1e18;
    }

    /// @notice Simulates a corporate event: a split or a dividend reinvestment.
    function setMultiplier(uint256 m) external {
        multiplier = m;
    }

    function mintShares(address to, uint256 shares) external {
        _shares[to] += shares;
        totalShares += shares;
    }

    function _toShares(uint256 amount) internal view returns (uint256) {
        return (amount * 1e18) / multiplier;
    }

    function approve(address s, uint256 a) external returns (bool) {
        allowance[msg.sender][s] = a;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        uint256 s = _toShares(amount);
        _shares[msg.sender] -= s;
        _shares[to] += s;
        return true;
    }

    function transferFrom(address f, address t, uint256 amount) external returns (bool) {
        uint256 al = allowance[f][msg.sender];
        if (al != type(uint256).max) allowance[f][msg.sender] = al - amount;
        uint256 s = _toShares(amount);
        _shares[f] -= s;
        _shares[t] += s;
        return true;
    }
}

/**
 * @notice A rebasing token that misbehaves on purpose.
 *
 * Two hazards observed on the real chain, reproduced: a proxy that returns
 * padded data for a selector it does not implement rather than reverting, and
 * a multiplier that can move at any point in a transaction including inside a
 * transfer.
 */
contract HostileRebasingToken {
    string public name = "Hostile xStock";
    string public symbol = "HOSTx";
    uint8 public decimals = 18;

    uint256 public multiplier = 1e18;
    uint256 public totalShares;
    mapping(address => uint256) private _shares;
    mapping(address => mapping(address => uint256)) public allowance;

    /// @dev 0 = normal, 1 = return 36 bytes of padded garbage, 2 = revert.
    uint8 public sharesMode;
    /// @dev Multiplier applied on the next transferFrom, 0 to disable.
    uint256 public rebaseOnTransferFrom;

    function setSharesMode(uint8 m) external { sharesMode = m; }
    function setMultiplier(uint256 m) external { multiplier = m; }
    function armRebaseOnTransferFrom(uint256 m) external { rebaseOnTransferFrom = m; }

    function mintShares(address to, uint256 s) external {
        _shares[to] += s;
        totalShares += s;
    }

    function balanceOf(address a) public view returns (uint256) {
        return (_shares[a] * multiplier) / 1e18;
    }

    function rawShares(address a) external view returns (uint256) { return _shares[a]; }

    /// @dev Mirrors the NVDAx proxy: unknown selectors return padded data
    ///      instead of reverting, so a caller that trusts the return decodes
    ///      nonsense.
    function sharesOf(address a) external view returns (uint256) {
        if (sharesMode == 2) revert("no sharesOf");
        if (sharesMode == 1) {
            assembly {
                mstore(0x00, 0xdeadbeef)
                mstore(0x20, 0xdeadbeef)
                mstore(0x40, 0xdeadbeef)
                return(0x00, 0x44)   // 68 bytes: not a uint256
            }
        }
        return _shares[a];
    }

    function approve(address s, uint256 a) external returns (bool) {
        allowance[msg.sender][s] = a;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        uint256 s = (amount * 1e18) / multiplier;
        _shares[msg.sender] -= s;
        _shares[to] += s;
        return true;
    }

    function transferFrom(address f, address t, uint256 amount) external returns (bool) {
        uint256 al = allowance[f][msg.sender];
        if (al != type(uint256).max) allowance[f][msg.sender] = al - amount;
        // The rebase lands AFTER the allowance is checked and debited but
        // BEFORE the share conversion, which is the tightest window available.
        if (rebaseOnTransferFrom != 0) {
            multiplier = rebaseOnTransferFrom;
            rebaseOnTransferFrom = 0;
        }
        uint256 s = (amount * 1e18) / multiplier;
        _shares[f] -= s;
        _shares[t] += s;
        return true;
    }
}

/**
 * @notice Configurable router. Every behaviour here is one the real aggregator
 *         could exhibit; none is assumed impossible.
 */
contract MockRouter {
    /// @dev Pulls `pull` of tokenIn from the caller and sends `give` of tokenOut.
    function swap(address tokenIn, address tokenOut, uint256 pull, uint256 give) external {
        if (pull > 0) IERC20(tokenIn).transferFrom(msg.sender, address(this), pull);
        if (give > 0) IERC20(tokenOut).transfer(msg.sender, give);
    }

    /// @dev Swaps, then fires a corporate event mid-transaction.
    function swapThenRebase(
        address tokenIn, address tokenOut, uint256 pull, uint256 give, uint256 newMultiplier
    ) external {
        if (pull > 0) IERC20(tokenIn).transferFrom(msg.sender, address(this), pull);
        if (give > 0) IERC20(tokenOut).transfer(msg.sender, give);
        MockRebasingToken(tokenOut).setMultiplier(newMultiplier);
    }

    /// @dev Fires the corporate event BEFORE delivering, so the delivered amount
    ///      is itself measured under the new multiplier.
    function rebaseThenSwap(
        address tokenIn, address tokenOut, uint256 pull, uint256 give, uint256 newMultiplier
    ) external {
        MockRebasingToken(tokenOut).setMultiplier(newMultiplier);
        if (pull > 0) IERC20(tokenIn).transferFrom(msg.sender, address(this), pull);
        if (give > 0) IERC20(tokenOut).transfer(msg.sender, give);
    }

    /// @dev Swaps and leaves dust in a third token — a route wrapper, in practice.
    function swapLeavingDust(
        address tokenIn, address tokenOut, uint256 pull, uint256 give,
        address dustToken, uint256 dust
    ) external {
        if (pull > 0) IERC20(tokenIn).transferFrom(msg.sender, address(this), pull);
        if (give > 0) IERC20(tokenOut).transfer(msg.sender, give);
        if (dust > 0) IERC20(dustToken).transfer(msg.sender, dust);
    }

    /// @dev Swaps, then calls an arbitrary target mid-transaction. Lets a fork
    ///      test drive a real token's storage (a forced rebase) from inside the
    ///      swap, which a mock cannot do to a deployed contract.
    function swapThenCall(
        address tokenIn, address tokenOut, uint256 pull, uint256 give,
        address target, bytes calldata cd
    ) external {
        if (pull > 0) IERC20(tokenIn).transferFrom(msg.sender, address(this), pull);
        if (give > 0) IERC20(tokenOut).transfer(msg.sender, give);
        (bool ok,) = target.call(cd);
        require(ok, "callback failed");
    }

    /// @dev Swaps, then fires TWO corporate events within the one transaction.
    function swapThenRebaseTwice(
        address tokenIn, address tokenOut, uint256 pull, uint256 give,
        uint256 first, uint256 second
    ) external {
        if (pull > 0) IERC20(tokenIn).transferFrom(msg.sender, address(this), pull);
        MockRebasingToken(tokenOut).setMultiplier(first);
        if (give > 0) IERC20(tokenOut).transfer(msg.sender, give);
        MockRebasingToken(tokenOut).setMultiplier(second);
    }

    function boom(string calldata reason) external pure {
        revert(reason);
    }

    receive() external payable {}
}
