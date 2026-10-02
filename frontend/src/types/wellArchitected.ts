export interface DocCitation {
  title: string;
  url: string;
  excerpt: string;
}

export interface WellArchitectedAnswer {
  question: string;
  answer: string;
  citations: DocCitation[];
  grounded: boolean;
  generated_by: string;
  generated_at: string;
}
