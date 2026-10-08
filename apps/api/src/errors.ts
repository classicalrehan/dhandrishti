export class AppError extends Error {
  constructor(
    readonly statusCode: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export class NotFoundError extends AppError {
  constructor(message: string) {
    super(404, "NOT_FOUND", message);
  }
}

/** No successful scoring run exists yet — the worker pipeline has not been run. */
export class NoDataError extends AppError {
  constructor(message = "No scored data available yet. Run the worker pipeline (pnpm pipeline:daily).") {
    super(503, "NO_DATA", message);
  }
}
