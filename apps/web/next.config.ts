import type { NextConfig } from "next";

/** Local hostnames allowed to load the dev server (see /etc/hosts setup in README). */
const devHosts = (process.env.DD_DEV_HOSTS ?? "dhandrishti.test,dhandrishti.localhost").split(",").map((h) => h.trim());

const config: NextConfig = {
  transpilePackages: ["@dd/contracts", "@dd/shared", "@dd/config"],
  poweredByHeader: false,
  allowedDevOrigins: devHosts,
};

export default config;
