import { Page } from "@playwright/test";

import { AgentDataSupport } from "./agent-data-support.po";
import { AuthSupport } from "./auth-support.po";
import { CommunicationConnectionDataSupport } from "./communication-connection-data-support.po";
import { EventDeliveryDataSupport } from "./event-delivery-data-support.po";
import { OrganizationDataSupport } from "./organization-data-support.po";
import { PlatformStatsDataSupport } from "./platform-stats-data-support.po";
import { PlatformTemplateDataSupport } from "./platform-template-data-support.po";
import { SkillDataSupport } from "./skill-data-support.po";
import { UserDataSupport } from "./user-data-support.po";

export class DataSupport {
  public auth: AuthSupport;
  public users: UserDataSupport;
  public agents: AgentDataSupport;
  public communicationConnections: CommunicationConnectionDataSupport;
  public skills: SkillDataSupport;
  public organizations: OrganizationDataSupport;
  public eventDeliveries: EventDeliveryDataSupport;
  public platformTemplates: PlatformTemplateDataSupport;
  public platformStats: PlatformStatsDataSupport;

  constructor(page: Page) {
    this.auth = new AuthSupport(page);
    this.users = new UserDataSupport(page);
    this.agents = new AgentDataSupport(page);
    this.communicationConnections = new CommunicationConnectionDataSupport(page);
    this.skills = new SkillDataSupport(page);
    this.organizations = new OrganizationDataSupport(page);
    this.eventDeliveries = new EventDeliveryDataSupport(page);
    this.platformTemplates = new PlatformTemplateDataSupport(page);
    this.platformStats = new PlatformStatsDataSupport(page);
  }
}
