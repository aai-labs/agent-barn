export const artifactFixture = {
  id: "a4150000-0000-4000-8000-000000000001",
  filename: "pipeline.csv", content_type: "text/csv", size: 24,
  checksum: "a".repeat(64), state: "READY", source: "chat",
  published_at: "2026-10-21T10:00:00Z", workflow_id: null,
  run_id: null, step_id: null, attempt_id: null,
};

export const fileIconFixtures = [
  ["quarterly-report.pdf", "application/pdf"],
  ["products.csv", "application/octet-stream"],
  ["product-photo.png", "image/png"],
  ["source-files.zip", "application/zip"],
  ["project-data.bin", "application/octet-stream"],
].map(([filename, content_type], index) => ({...artifactFixture, id: `file-icon-${index}`, filename, content_type}));
