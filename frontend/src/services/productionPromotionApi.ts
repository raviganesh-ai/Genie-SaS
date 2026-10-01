import { apiFetch } from "./httpClient";
import type { ProductionPromotion } from "@/types/productionPromotion";

export const productionPromotionApi = {
  list(sessionId: string): Promise<ProductionPromotion[]> {
    return apiFetch<ProductionPromotion[]>(
      `/sessions/${sessionId}/production-promotions`,
    );
  },

  create(
    sessionId: string,
    request: {
      deployment_run_id: string;
      resource_group_name: string;
      backend_app_name: string;
      health_url: string;
    },
  ): Promise<ProductionPromotion> {
    return apiFetch<ProductionPromotion>(
      `/sessions/${sessionId}/production-promotions`,
      { method: "POST", body: request },
    );
  },

  rehearse(sessionId: string, promotionId: string): Promise<ProductionPromotion> {
    return apiFetch<ProductionPromotion>(
      `/sessions/${sessionId}/production-promotions/${promotionId}/rehearse`,
      { method: "POST" },
    );
  },

  promote(sessionId: string, promotionId: string): Promise<ProductionPromotion> {
    return apiFetch<ProductionPromotion>(
      `/sessions/${sessionId}/production-promotions/${promotionId}/promote`,
      { method: "POST" },
    );
  },
};

