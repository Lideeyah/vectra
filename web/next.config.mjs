/**
 * The fork-data guard, enforced where the build actually happens.
 *
 * CI already fails if NEXT_PUBLIC_ALLOW_FORK_HISTORY is set, but CI is not the
 * host. A hosting provider has its own environment panel, and a default that
 * can be overridden in one place nobody checks is not a default — it is a
 * convention. So the check runs inside the production build itself: wherever
 * that build happens, on whatever machine, with whatever environment, setting
 * this flag stops the deploy rather than shipping fork transactions.
 *
 * Development is untouched. `next dev` runs with NODE_ENV=development and the
 * flag is how fork legs are viewed locally; only a production build refuses.
 */
if (
  process.env.NODE_ENV === "production" &&
  process.env.NEXT_PUBLIC_ALLOW_FORK_HISTORY === "true"
) {
  throw new Error(
    "NEXT_PUBLIC_ALLOW_FORK_HISTORY is set to true in a production build.\n" +
      "\n" +
      "That flag reveals fork-origin legs — real swaps through the real router,\n" +
      "but transactions that do not exist on X Layer. Shipping them would put a\n" +
      "table of unreal transactions in front of anyone deciding whether to trust\n" +
      "this, and the banner explaining them is not carried by a screenshot.\n" +
      "\n" +
      "Unset it in the host's environment settings and redeploy.",
  );
}

/** @type {import('next').NextConfig} */
export default { reactStrictMode: true };
