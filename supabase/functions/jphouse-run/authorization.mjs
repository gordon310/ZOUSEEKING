export function isQueryOwnedByUser(query, userId) {
  const ownerUserId = typeof query?.owner_user_id === "string" ? query.owner_user_id.trim() : "";
  const authenticatedUserId = typeof userId === "string" ? userId.trim() : "";
  return Boolean(ownerUserId && authenticatedUserId && ownerUserId === authenticatedUserId);
}

export function isLegacyExecutionEnabled(value) {
  return value === "true";
}
