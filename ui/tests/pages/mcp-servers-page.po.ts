import type { Page } from "@playwright/test";

/** Organization settings → MCP servers, its add/edit dialog, and an Agent's MCP section. */
export class McpServersPage {
  constructor(private page: Page) {}

  get list() { return this.page.getByRole("list", { name: "MCP servers", exact: true }); }
  get addButton() { return this.page.getByRole("button", { name: "Add MCP server", exact: true }); }
  get dialog() { return this.page.getByRole("dialog"); }
  get tools() { return this.dialog.getByRole("region", { name: "Tools", exact: true }); }
  field(label: string) { return this.dialog.getByLabel(label, { exact: true }); }
  tool(name: string) { return this.dialog.getByRole("checkbox", { name: `${name} visible to Agents` }); }
  editButton(name: string) { return this.page.getByRole("button", { name: `Edit ${name}`, exact: true }); }
  deleteButton(name: string) { return this.page.getByRole("button", { name: `Delete ${name}`, exact: true }); }

  async selectAuth(option: string) {
    await this.field("Authentication").click();
    await this.page.getByRole("option", { name: option, exact: true }).click();
  }
  async testConnection() { await this.dialog.getByRole("button", { name: "Test connection" }).click(); }
  async chooseAllAgents() { await this.dialog.getByRole("radio", { name: /All Agents/ }).check(); }
  async submit(label: "Add server" | "Save changes") { await this.dialog.getByRole("button", { name: label, exact: true }).click(); }


  // Agent configuration → MCP servers.
  // Beside the section's heading, outside both groups.
  get addOwnServerButton() { return this.page.getByRole("button", { name: "Add server for this Agent" }); }
  get ownServers() { return this.page.getByRole("region", { name: "This Agent's own MCP servers", exact: true }); }
  get agentSection() { return this.page.getByRole("region", { name: "MCP servers", exact: true }); }
  agentSwitch(name: string) { return this.agentSection.getByRole("switch", { name: `${name} for this Agent` }); }
  agentRow(name: string) { return this.agentSection.getByRole("listitem").filter({ hasText: name }); }
  serverRow(name: string) { return this.list.getByRole("listitem").filter({ hasText: name }); }
  get applyButton() { return this.agentSection.getByRole("button", { name: /^Apply(?: & Restart)?$/ }); }
  async applyAgent() {
    await this.agentSection.getByRole("button", { name: /^Apply(?: & Restart)?$/ }).click();
    await this.dialog.getByRole("button", { name: /^Apply(?: & Restart)?$/ }).click();
    await this.dialog.waitFor({ state: "hidden" });
  }
}
