"use client";

import { OrganizationCombobox } from "@/components/organization-combobox";

interface EventDeliveryOrganizationComboboxProps {
  organizationId: string | null;
  organizationName: string | null;
  onChange: (organization: { id: string; name: string } | null) => void;
}

/** Thin wrapper so this feature's call sites keep their own naming. */
export function EventDeliveryOrganizationCombobox(
  props: EventDeliveryOrganizationComboboxProps,
) {
  return <OrganizationCombobox {...props} />;
}
