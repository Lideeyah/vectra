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

    function boom(string calldata reason) external pure {
        revert(reason);
    }

    receive() external payable {}
}
