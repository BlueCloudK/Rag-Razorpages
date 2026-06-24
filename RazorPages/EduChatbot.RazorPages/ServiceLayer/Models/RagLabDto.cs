using System;
using System.Collections.Generic;

namespace ServiceLayer.Models
{
    public class RagLabDashboardDto
    {
        public bool HasReport { get; set; }
        public string AiServicePath { get; set; } = string.Empty;
        public string ReportPath { get; set; } = string.Empty;
        public DateTime? ReportGeneratedAt { get; set; }
        public int SubjectId { get; set; }
        public int TotalCases { get; set; }
        public int PassedCases { get; set; }
        public double QualityScore { get; set; }
        public double ProductionScore { get; set; }
        public int DocumentCount { get; set; }
        public int ChunkCount { get; set; }
        public string EmbeddingModel { get; set; } = "Qwen/Qwen3-Embedding-0.6B";
        public string AnswerModel { get; set; } = "gemma3:4b";
        public string ChromaCollection { get; set; } = "edu_documents";
        public List<RagLabDocumentDto> Documents { get; set; } = new();
        public List<RagLabMetricDto> Metrics { get; set; } = new();
        public List<RagLabGroupDto> Groups { get; set; } = new();
        public List<RagLabCaseDto> FailedCases { get; set; } = new();
        public List<RagLabCaseDto> GoodExamples { get; set; } = new();
        public List<string> PipelineSteps { get; set; } = new();
        public List<string> DemoCommands { get; set; } = new();
    }

    public class RagLabDocumentDto
    {
        public string Name { get; set; } = string.Empty;
        public int Chunks { get; set; }
    }

    public class RagLabMetricDto
    {
        public string Name { get; set; } = string.Empty;
        public double Score { get; set; }
        public string Description { get; set; } = string.Empty;
    }

    public class RagLabGroupDto
    {
        public string Name { get; set; } = string.Empty;
        public int Passed { get; set; }
        public int Total { get; set; }
        public double QualityScore { get; set; }
        public double ProductionScore { get; set; }
    }

    public class RagLabCaseDto
    {
        public string Id { get; set; } = string.Empty;
        public string Group { get; set; } = string.Empty;
        public string Question { get; set; } = string.Empty;
        public string Answer { get; set; } = string.Empty;
        public bool Passed { get; set; }
        public List<string> Failures { get; set; } = new();
    }
}
