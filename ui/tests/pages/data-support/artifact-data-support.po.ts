import type { Page } from "@playwright/test";
import { artifactFixture } from "../../fixtures/artifacts";

export class ArtifactDataSupport {
  storageState = "READY";
  provisionRequests = 0;
  provisionDenied = false;
  downloadFailure: {id: string; detail: string; status: number} | undefined;
  failPage: number | undefined;
  requestedPages: number[] = [];
  deleteRequests = 0;
  deleteFailure: {status: number; detail: string} | undefined;
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
      if (url.pathname.endsWith("/storage")) {
        if (route.request().method() === "POST") {
          this.provisionRequests++;
          if (this.provisionDenied) {
            await route.fulfill({status: 403, json: {detail: "Agent update access required"}}); return;
          }
          this.storageState = "PROVISIONING";
          await route.fulfill({status: 202, json: {state: this.storageState}}); return;
        }
        await route.fulfill({json: {state: this.storageState}}); return;
      }
      if (this.listDenied || (this.denied && url.pathname.endsWith("download-link"))) {
        await route.fulfill({status: 404, json: {detail: "Artifact not found"}}); return;
      }
      if (url.pathname.endsWith("download-link")) {
        if (this.downloadFailure && url.pathname.includes(this.downloadFailure.id)) {
          await route.fulfill({status: this.downloadFailure.status, json: {detail: this.downloadFailure.detail}}); return;
        }
        this.links++;
        await route.fulfill({json: {artifact: this.files[0], url: this.downloadUrl ?? `http://127.0.0.1:3003/test-artifact-download?signature=${this.links}`, expires_at: "2026-10-21T10:15:00Z"}}); return;
      }
      if (route.request().method() === "DELETE") {
        this.deleteRequests++;
        if (this.deleteFailure) {
          await route.fulfill({status: this.deleteFailure.status, json: {detail: this.deleteFailure.detail}}); return;
        }
        const id = url.pathname.split("/").pop();
        this.files = this.files.filter(file => file.id !== id);
        await route.fulfill({status: 204}); return;
      }
      this.lists++;
      const requestedPage = Number(url.searchParams.get("page") ?? 1);
      const pageSize = Number(url.searchParams.get("page_size") ?? 20);
      this.requestedPages.push(requestedPage);
      if (this.failPage === requestedPage) {
        await route.fulfill({status: 503, json: {detail: "File listing temporarily unavailable"}}); return;
      }
      const stepId = url.searchParams.get("step_id");
      const items = this.files.filter(file => !stepId || file.step_id === stepId);
      await route.fulfill({json: {items: items.slice((requestedPage - 1) * pageSize, requestedPage * pageSize), total: items.length, page: requestedPage, page_size: pageSize}});
    });
    await this.page.route("**/test-artifact-download?*", route => route.fulfill({
      status: 200, contentType: "application/octet-stream", headers: {"Content-Disposition": "attachment; filename=pipeline.csv"}, body: "actual downloaded bytes",
    }));
  }
}
