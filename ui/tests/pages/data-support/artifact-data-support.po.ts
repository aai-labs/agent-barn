import type { Page } from "@playwright/test";
import { artifactFixture } from "../../fixtures/artifacts";

export class ArtifactDataSupport {
  links = 0;
  lists = 0;
  downloadUrl: string | undefined;
  denied = false;
  listDenied = false;
  files: Array<Omit<typeof artifactFixture, "run_id" | "step_id" | "attempt_id"> & {run_id: string | null; step_id: string | null; attempt_id: string | null}> = [artifactFixture];
  constructor(private page: Page) {}
  async intercept(agentId: string) {
    await this.page.route(`**/api/v1/organizations/*/agents/${agentId}/artifacts**`, async route => {
      const url = new URL(route.request().url());
      if (this.listDenied || (this.denied && url.pathname.endsWith("download-link"))) {
        await route.fulfill({status: 404, json: {detail: "Artifact not found"}}); return;
      }
      if (url.pathname.endsWith("download-link")) {
        this.links++;
        await route.fulfill({json: {artifact: this.files[0], url: this.downloadUrl ?? `http://127.0.0.1:3003/test-artifact-download?signature=${this.links}`, expires_at: "2026-10-21T10:15:00Z"}}); return;
      }
      this.lists++;
      const stepId = url.searchParams.get("step_id");
      const items = this.files.filter(file => !stepId || file.step_id === stepId);
      await route.fulfill({json: {items, total: items.length, page: 1, page_size: 20}});
    });
    await this.page.route("**/test-artifact-download?*", route => route.fulfill({
      status: 200, contentType: "application/octet-stream", headers: {"Content-Disposition": "attachment; filename=pipeline.csv"}, body: "actual downloaded bytes",
    }));
  }
}
