import type { NextFunction, Request, Response } from "express";

/** An error carrying an HTTP status. Message is safe to return to clients. */
export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "HttpError";
  }
}

export const badRequest = (m: string) => new HttpError(400, m);
export const unauthorized = (m = "Unauthorized") => new HttpError(401, m);
export const forbidden = (m = "Forbidden") => new HttpError(403, m);
export const notFound = (m = "Not found") => new HttpError(404, m);
export const conflict = (m: string) => new HttpError(409, m);

/** Wrap an async route handler so rejected promises reach the error handler. */
export function asyncHandler(
  fn: (req: Request, res: Response, next: NextFunction) => Promise<unknown>,
) {
  return (req: Request, res: Response, next: NextFunction) => {
    fn(req, res, next).catch(next);
  };
}

/**
 * Central error handler. Always JSON, never HTML, never a stack trace to the
 * client (PRD Section 11). Unknown errors become a generic 500.
 */
export function errorHandler(
  err: unknown,
  _req: Request,
  res: Response,
  _next: NextFunction,
): void {
  if (err instanceof HttpError) {
    res.status(err.status).json({ message: err.message });
    return;
  }
  // Never leak internals. Log server-side only.
  console.error("[unhandled]", err instanceof Error ? err.stack : err);
  res.status(500).json({ message: "Internal server error" });
}

/** JSON 404 for unknown API paths. */
export function notFoundHandler(_req: Request, res: Response): void {
  res.status(404).json({ message: "Not found" });
}
