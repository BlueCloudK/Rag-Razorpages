namespace DataAccessLayer.Models
{
    public class QuestionUsage
    {
        public int Id { get; set; }
        public string UserId { get; set; } = string.Empty;
        public ApplicationUser? User { get; set; }
        public int? OrganizationId { get; set; }
        public Organization? Organization { get; set; }
        public DateTime UsageDate { get; set; }
        public int QuestionCount { get; set; }
    }
}
