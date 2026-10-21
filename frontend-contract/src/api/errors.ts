export class ApiError extends Error {
  constructor(
    public kind:
      | "network"
      | "timeout"
      | "server"
      | "unauthorized"
      | "validation"
      | "not_found"
      | "contract",
    message: string,
    /** Техническая подпись: какой запрос и что пошло не так, например «PATCH /api/records/5 → 404» */
    public detail = "",
  ) {
    super(message);
    this.name = "ApiError";
  }
}
