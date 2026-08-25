/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // PAPYRUS_API_URL and PAPYRUS_MAX_UPLOAD_BYTES are read at request time in
  // the route handlers, not inlined here — inlining would bake the build
  // machine's value into the bundle and make the deployed engine URL
  // impossible to change without a rebuild.
};

export default nextConfig;
