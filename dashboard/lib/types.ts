export interface Signal {
  signal_id: string;
  source: string;
  title: string;
  entity: string;
  date: string | null;
  category: string | null;
  url: string;
  summary: string | null;
  relevance_score: number;
  impact_direction: string | null;
  sectors: string[];
  correlated_sources: string[];
  fetched_at: string;
}

export const SOURCES = ["SEC_EDGAR", "FEDERAL_REGISTER", "USASPENDING", "CONGRESS"] as const;
