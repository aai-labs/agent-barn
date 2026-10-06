// The pinned plugin uses generic hooks/tools and must coexist with memory-core.
import fs from "node:fs";

const manifestPath = process.argv[2];
const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
if (manifest.id !== "hindsight-openclaw" || manifest.kind !== "memory") {
  throw new Error("Pinned Hindsight plugin manifest changed; review memory-slot compatibility.");
}
delete manifest.kind;
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
