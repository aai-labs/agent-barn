"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/shared/api";
import { currentUserContextKey } from "@/auth/utils";

import {
  type AddMemberFormData,
  type InviteLinkResult,
  InviteLinkResultSchema,
  type MemberInviteResult,
  MemberInviteResultSchema,
  type OrganizationRole,
} from "../schemas";
import { organizationMembersKey } from "../utils";

export function useMemberActions(organizationId: string) {
  const queryClient = useQueryClient();
  const base = `/api/v1/organizations/${organizationId}`;

  const invalidateMembers = () =>
    queryClient.invalidateQueries({
      queryKey: organizationMembersKey.list({ scope: { organizationId } }),
    });

  const addMember = useMutation({
    mutationFn: async (data: AddMemberFormData) => {
      const response = await api.post<MemberInviteResult>(
        `${base}/members`,
        data,
        { schema: MemberInviteResultSchema },
      );
      return response.data;
    },
    onSuccess: invalidateMembers,
  });

  const changeRole = useMutation({
    mutationFn: (vars: { userId: string; role: OrganizationRole }) =>
      api.patch(`${base}/members/${vars.userId}`, { role: vars.role }),
    onSuccess: invalidateMembers,
  });

  const removeMember = useMutation({
    mutationFn: (userId: string) => api.delete(`${base}/members/${userId}`),
    onSuccess: invalidateMembers,
  });

  const transferOwnership = useMutation({
    mutationFn: (userId: string) =>
      api.post(`${base}/transfer-ownership`, { userId }),
    onSuccess: () => {
      invalidateMembers();
      // Ownership changes affect the acting user's own role, so refresh their context.
      void queryClient.invalidateQueries({ queryKey: currentUserContextKey.all });
    },
  });

  const resendInvite = useMutation({
    mutationFn: async (userId: string) => {
      const response = await api.post<InviteLinkResult>(
        `${base}/members/${userId}/resend-invite`,
        undefined,
        { schema: InviteLinkResultSchema },
      );
      return response.data;
    },
  });

  return { addMember, changeRole, removeMember, transferOwnership, resendInvite };
}
