# Paperclip — Coolify Deployment

## Deploy URL
https://buildr.theAiBuildr.com

## Quick Reference

### Environment Setup
1. Copy `.env.example` values into Coolify Environment Variables tab
2. Fill in all `[PLACEHOLDER]` values
3. Generate `BETTER_AUTH_SECRET` with: `openssl rand -hex 32`

### Post-Deploy Commands
```bash
# Fix permissions (run on server once)
chown -R 1000:1000 /data/coolify/applications/YOUR_APP_UUID

# Run database migrations
CONTAINER_ID=$(docker ps -q --filter "publish=3100")
docker exec -e DATABASE_URL="YOUR_DIRECT_DB_URL_PORT_5432" -it --user node $CONTAINER_ID npx drizzle-kit push

# Onboard
docker exec -it --user node $CONTAINER_ID pnpm paperclipai onboard