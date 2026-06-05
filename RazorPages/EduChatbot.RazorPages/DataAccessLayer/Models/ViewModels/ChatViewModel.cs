using System.Collections.Generic;
using DataAccessLayer.Models;

namespace DataAccessLayer.Models.ViewModels
{
    public class ChatViewModel
    {
        public ChatSession? CurrentSession { get; set; }
        public IEnumerable<Document>? CurrentDocuments { get; set; }
    }
}


