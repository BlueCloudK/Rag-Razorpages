using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Microsoft.Extensions.Hosting;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public class RagLabService : IRagLabService
    {
        private readonly IHostEnvironment _environment;

        public RagLabService(IHostEnvironment environment)
        {
            _environment = environment;
        }

        public async Task<RagLabDashboardDto> GetDashboardAsync()
        {
            var aiServicePath = ResolveAiServiceDirectory();
            var dashboard = new RagLabDashboardDto
            {
                AiServicePath = aiServicePath ?? string.Empty,
                PipelineSteps = BuildPipelineSteps(),
                DemoCommands = BuildDemoCommands(aiServicePath)
            };

            if (string.IsNullOrWhiteSpace(aiServicePath))
            {
                return dashboard;
            }

            var latestReport = FindLatestBenchmarkReport(aiServicePath);
            if (latestReport is null)
            {
                return dashboard;
            }

            dashboard.HasReport = true;
            dashboard.ReportPath = latestReport.FullName;
            dashboard.ReportGeneratedAt = latestReport.LastWriteTime;

            await using var stream = latestReport.OpenRead();
            using var document = await JsonDocument.ParseAsync(stream);
            var root = document.RootElement;

            dashboard.SubjectId = GetInt(root, "subject_id");
            dashboard.QualityScore = GetDouble(root, "quality_score");
            dashboard.ProductionScore = GetDouble(root, "production_score");

            if (root.TryGetProperty("cases", out var casesElement) && casesElement.ValueKind == JsonValueKind.Array)
            {
                var cases = casesElement.EnumerateArray().ToList();
                dashboard.TotalCases = cases.Count;
                dashboard.PassedCases = cases.Count(item => GetBool(item, "passed"));
                dashboard.FailedCases = cases
                    .Where(item => !GetBool(item, "passed"))
                    .Take(6)
                    .Select(ToCaseDto)
                    .ToList();
                dashboard.GoodExamples = cases
                    .Where(item => GetBool(item, "passed") && HasGroundedAnswer(item))
                    .Take(4)
                    .Select(ToCaseDto)
                    .ToList();
                dashboard.Metrics = BuildMetricSummary(cases);
                dashboard.Documents = ExtractDocuments(cases);
                dashboard.DocumentCount = dashboard.Documents.Count;
                dashboard.ChunkCount = dashboard.Documents.Sum(item => item.Chunks);
            }

            if (root.TryGetProperty("group_summary", out var groupsElement) && groupsElement.ValueKind == JsonValueKind.Object)
            {
                dashboard.Groups = groupsElement.EnumerateObject()
                    .Select(group => new RagLabGroupDto
                    {
                        Name = NormalizeGroupName(group.Name),
                        Passed = GetInt(group.Value, "passed"),
                        Total = GetInt(group.Value, "total"),
                        QualityScore = GetDouble(group.Value, "quality_score"),
                        ProductionScore = GetDouble(group.Value, "production_score")
                    })
                    .OrderBy(item => item.Name)
                    .ToList();
            }

            return dashboard;
        }

        private string? ResolveAiServiceDirectory()
        {
            var candidates = new[]
            {
                Path.Combine(_environment.ContentRootPath, "..", "..", "..", "AIServices", "AiService"),
                Path.Combine(_environment.ContentRootPath, "..", "..", "..", "..", "AIServices", "AiService"),
                Path.Combine(Directory.GetCurrentDirectory(), "..", "..", "..", "AIServices", "AiService"),
                Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "..", "AIServices", "AiService")
            };

            return candidates
                .Select(path => Path.GetFullPath(path))
                .FirstOrDefault(path => Directory.Exists(path) && File.Exists(Path.Combine(path, "main.py")));
        }

        private static FileInfo? FindLatestBenchmarkReport(string aiServicePath)
        {
            var resultDir = Path.Combine(aiServicePath, "data", "benchmark_results");
            if (!Directory.Exists(resultDir))
            {
                return null;
            }

            return new DirectoryInfo(resultDir)
                .EnumerateFiles("demo-rag-*.json")
                .OrderByDescending(file => file.LastWriteTimeUtc)
                .FirstOrDefault();
        }

        private static List<string> BuildPipelineSteps()
        {
            return new()
            {
                "Adaptive chunking scores page-aware, structured-heading, and recursive strategies.",
                "Contextual retrieval embeds rule-based context while citations still show original text.",
                "Vector, keyword, and metadata branches search in parallel and merge with RRF/scoring.",
                "Evidence scorer selects bounded context windows and separates matched chunk from context sent.",
                "Local LLM answers from selected evidence only; citation check exposes sources used."
            };
        }

        private static List<string> BuildDemoCommands(string? aiServicePath)
        {
            var path = string.IsNullOrWhiteSpace(aiServicePath) ? @"D:\Project\rag-razorpages\AIServices\AiService" : aiServicePath;
            return new()
            {
                $@"cd {path}",
                @"python .\index_demo_documents.py --reset --subject-id 1007",
                @"python .\run_demo_benchmark.py --subject-id 1007",
                @"python .\run_demo_benchmark.py --subject-id 1007 --group safety,weird_input,ambiguous"
            };
        }

        private static RagLabCaseDto ToCaseDto(JsonElement element)
        {
            var failures = new List<string>();
            if (element.TryGetProperty("failures", out var failuresElement) && failuresElement.ValueKind == JsonValueKind.Array)
            {
                failures = failuresElement.EnumerateArray()
                    .Select(item => item.GetString() ?? string.Empty)
                    .Where(item => !string.IsNullOrWhiteSpace(item))
                    .ToList();
            }

            return new RagLabCaseDto
            {
                Id = GetString(element, "id"),
                Group = NormalizeGroupName(GetString(element, "group")),
                Question = GetString(element, "question"),
                Answer = Truncate(GetString(element, "answer"), 260),
                Passed = GetBool(element, "passed"),
                Failures = failures
            };
        }

        private static bool HasGroundedAnswer(JsonElement element)
        {
            if (GetString(element, "retrieval_strategy").Contains("blocked", StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }

            if (element.TryGetProperty("contexts", out var contexts) && contexts.ValueKind == JsonValueKind.Array && contexts.GetArrayLength() > 0)
            {
                return true;
            }

            return GetString(element, "retrieval_strategy") is "document_list" or "document_summary_metadata";
        }

        private static List<RagLabMetricDto> BuildMetricSummary(List<JsonElement> cases)
        {
            var metricNames = new Dictionary<string, string>
            {
                ["retrieval_hit"] = "Retrieved expected evidence when the case required document grounding.",
                ["source_correctness"] = "Cited the expected source file or avoided source when blocked.",
                ["citation_precision"] = "Attached citations only from selected evidence.",
                ["answer_coverage"] = "Covered the requested answer points.",
                ["hallucination_flag"] = "Avoided unsupported answers and fake sources.",
                ["conflict_handling"] = "Reported conflicts between original and modified documents.",
                ["duplicate_handling"] = "Merged duplicate evidence without inventing conflict.",
                ["language_quality"] = "Kept Vietnamese/English output clean and style-safe."
            };

            return metricNames
                .Select(metric =>
                {
                    var values = cases
                        .Select(item => GetMetric(item, metric.Key))
                        .Where(value => value.HasValue)
                        .Select(value => value!.Value)
                        .ToList();
                    return new RagLabMetricDto
                    {
                        Name = NormalizeGroupName(metric.Key),
                        Score = values.Count == 0 ? 0 : Math.Round(values.Average(), 3),
                        Description = metric.Value
                    };
                })
                .ToList();
        }

        private static double? GetMetric(JsonElement element, string metricName)
        {
            if (!element.TryGetProperty("production_metrics", out var metrics) || metrics.ValueKind != JsonValueKind.Object)
            {
                return null;
            }

            return metrics.TryGetProperty(metricName, out var value) ? GetDouble(value) : null;
        }

        private static List<RagLabDocumentDto> ExtractDocuments(List<JsonElement> cases)
        {
            var docListCase = cases.FirstOrDefault(item => GetString(item, "id") == "doc_list_vi");
            var answer = GetString(docListCase, "answer");
            var documents = new List<RagLabDocumentDto>();
            foreach (Match match in Regex.Matches(answer, @"\*\*(?<name>[^*]+\.pdf)\*\*\s+\((?<chunks>\d+)\s+"))
            {
                documents.Add(new RagLabDocumentDto
                {
                    Name = match.Groups["name"].Value,
                    Chunks = int.TryParse(match.Groups["chunks"].Value, out var chunks) ? chunks : 0
                });
            }

            return documents;
        }

        private static string NormalizeGroupName(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return "Unknown";
            }

            return CultureInfo.InvariantCulture.TextInfo.ToTitleCase(value.Replace("_", " ").Replace("-", " "));
        }

        private static string Truncate(string value, int maxLength)
        {
            if (string.IsNullOrWhiteSpace(value) || value.Length <= maxLength)
            {
                return value;
            }

            return value[..maxLength].TrimEnd() + "...";
        }

        private static string GetString(JsonElement element, string propertyName)
        {
            if (element.ValueKind == JsonValueKind.Undefined || element.ValueKind == JsonValueKind.Null)
            {
                return string.Empty;
            }

            return element.TryGetProperty(propertyName, out var value) && value.ValueKind == JsonValueKind.String
                ? value.GetString() ?? string.Empty
                : string.Empty;
        }

        private static int GetInt(JsonElement element, string propertyName)
        {
            if (!element.TryGetProperty(propertyName, out var value))
            {
                return 0;
            }

            return GetInt(value);
        }

        private static int GetInt(JsonElement value)
        {
            if (value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out var result))
            {
                return result;
            }

            return 0;
        }

        private static double GetDouble(JsonElement element, string propertyName)
        {
            if (!element.TryGetProperty(propertyName, out var value))
            {
                return 0;
            }

            return GetDouble(value);
        }

        private static double GetDouble(JsonElement value)
        {
            if (value.ValueKind == JsonValueKind.Number && value.TryGetDouble(out var result))
            {
                return Math.Round(result, 3);
            }

            return 0;
        }

        private static bool GetBool(JsonElement element, string propertyName)
        {
            return element.TryGetProperty(propertyName, out var value)
                && value.ValueKind is JsonValueKind.True or JsonValueKind.False
                && value.GetBoolean();
        }
    }
}
