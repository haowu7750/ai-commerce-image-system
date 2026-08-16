const SERVICE_ID = "ai-commerce-operations-frontend";

export function GET() {
  return Response.json({
    service: SERVICE_ID,
    environment: process.env.NODE_ENV ?? "development",
    status: "ok",
  });
}
