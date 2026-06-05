namespace DataAccessLayer.Models
{
    public class SubjectMembership
    {
        public int Id { get; set; }
        public int SubjectId { get; set; }
        public Subject? Subject { get; set; }
        public string UserId { get; set; } = string.Empty;
        public ApplicationUser? User { get; set; }
        public string RoleInSubject { get; set; } = string.Empty;
    }
}
