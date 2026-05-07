import type { ZodType } from "zod";
import { ZodError } from "zod";
import { ApiError } from "./error/errors";

export const validateResponse = async <T>(
  data: any,
  schema: ZodType<T, any, any>,
): Promise<T> => {
  try {
    return schema.parse(data);
  } catch (error) {
    if (error instanceof ZodError) {
      throw ApiError.validationError("Response validation failed", {
        zodErrors: error.issues,
      });
    }
    throw error;
  }
};
