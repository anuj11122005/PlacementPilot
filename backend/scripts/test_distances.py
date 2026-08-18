import os
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

def main():
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    
    resume_chunks = [
        "Backend Engineer with 5 years of experience building Python microservices. Passionate about team collaboration, mentoring juniors, and delivering scalable systems.",
        "Skills: Python, FastAPI, SQL, Docker, AWS, Git.",
        "Software Engineer at TechCorp. Led a team of 3 developers to migrate a monolithic application to FastAPI microservices. Managed sprints and conducted code reviews.",
        "B.S. in Computer Science, State University."
    ]
    
    queries = [
        ("C1: Trap - Hallucinated metrics", "Led a team of 10+ developers"),
        ("C2: Trap - Hallucinated timeline", "10 years of experience building Python microservices"),
        ("C3: Trap - False Scope", "Architected monolithic applications"),
        ("C4: Trap - Unstated Proficiency", "Expert proficiency in AWS and Git"),
        ("C5: Trap - Role Assumption", "Passionate about mentoring 50+ juniors"),
        ("A2: Java/Spring mismatch", "Expertise in Java and Spring Boot"),
        ("B1: Java/Spring (wrong stack)", "Expertise in Java and Spring Boot")
    ]
    
    resume_emb = model.encode(resume_chunks)
    
    for label, q in queries:
        q_emb = model.encode([q])
        sims = cosine_similarity(q_emb, resume_emb)[0]
        max_sim = max(sims)
        print(f"{label}: max_sim = {max_sim:.3f}")

if __name__ == '__main__':
    main()
