# shadow_market/frontend/Dockerfile
# Revision History:
# 2025-04-07: Initial creation from scratch (one file at a time).
#             - Multi-stage build (builder/runtime).
#             - Uses node:18-alpine for builder stage (smaller Node image).
#             - Uses nginx:stable-alpine-slim for runtime stage (minimal, secure Nginx).
#             - Installs dependencies using yarn --frozen-lockfile.
#             - Builds frontend static assets using yarn build.
#             - Copies built assets from builder to nginx html directory.
#             - Copies a custom nginx.conf file (must be present in frontend dir).
#             - Configures nginx to run as non-root 'nginx' user (default in image).
#             - Exposes port 8080 (can be mapped externally).

# --- Builder Stage ---
# Use a specific stable Node.js Alpine tag for smaller size and security focus
FROM node:18-alpine AS builder

# Set working directory within the builder stage
WORKDIR /app

# Copy package.json and yarn.lock first to leverage Docker build cache
COPY package.json yarn.lock ./

# Install dependencies using yarn's frozen lockfile feature for build consistency
# Increase network timeout if needed for slow connections
RUN yarn install --frozen-lockfile --network-timeout 100000

# Copy the rest of the frontend application source code
COPY . .

# Build the production static files (e.g., into the 'build' directory)
# Pass build-time environment variables using ARG and ENV if necessary
# Example: ARG REACT_APP_API_URL
# Example: ENV REACT_APP_API_URL=$REACT_APP_API_URL
RUN yarn build


# --- Runtime Stage ---
# Use a minimal, security-focused Nginx Alpine image ('slim' variant is even smaller)
FROM nginx:stable-alpine-slim AS runtime

# Copy the custom Nginx configuration file from the build context
# This file should be located at 'shadow_market/frontend/nginx.conf'
COPY nginx.conf /etc/nginx/nginx.conf

# Copy built static assets from the builder stage's output directory (e.g., /app/build)
# to the default Nginx html directory
COPY --from=builder /app/build /usr/share/nginx/html

# Nginx official images already create and use a non-root 'nginx' user.
# We need to ensure permissions are correct for this user to read files and write logs/pid.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d \
    && chmod -R 755 /usr/share/nginx/html \
    && touch /var/run/nginx.pid && chown -R nginx:nginx /var/run/nginx.pid

# Switch to the non-root Nginx user explicitly (good practice)
USER nginx

# Expose the port specified in the nginx.conf 'listen' directive (e.g., 8080)
EXPOSE 8080

# Default command to run Nginx in the foreground
CMD ["nginx", "-g", "daemon off;"]