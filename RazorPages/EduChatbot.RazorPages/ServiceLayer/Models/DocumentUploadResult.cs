namespace ServiceLayer.Models
{
    public class DocumentUploadResult
    {
        public string Status { get; set; } = "Failed";
        public bool Indexed { get; set; }
        public int Chunks { get; set; }
        public string Message { get; set; } = string.Empty;
        public int DocumentId { get; set; }
        public string FileName { get; set; } = string.Empty;
        public string? ReturnUrl { get; set; }
    }
}
