import type { TaskAreaRecommendation, TaskItem, TasksLifeArea } from "./api.ts";


export type FocusRecommendation = {
  area: TasksLifeArea;
  sectionName: string;
  task: TaskItem | null;
  reason: string;
  taskCount: number;
  tasks: TaskItem[];
};

export type RecommendationSnapshot = {
  area: TasksLifeArea;
  provider: string | null;
  providerRecordId: string | null;
  taskContent: string | null;
};

export type RecommendationChange = {
  area: TasksLifeArea;
  previous: string;
  current: string;
  reason: string;
};


export function presentTaskRecommendations(items: TaskAreaRecommendation[]): FocusRecommendation[] {
  return items.map((item) => {
    const recommendation = item.recommendation;
    return {
      area: item.area,
      sectionName: item.section_name,
      task: recommendation?.task ?? null,
      reason:
        recommendation?.explanation
        ?? (item.state === "unavailable" ? "Todoist recommendations unavailable" : `No active ${item.area} tasks`),
      taskCount: item.task_count,
      tasks: recommendation
        ? [recommendation.task, ...recommendation.alternatives.map((alternative) => alternative.task)]
        : [],
    };
  });
}


export function recommendationSnapshots(items: TaskAreaRecommendation[]): RecommendationSnapshot[] {
  return items.map((item) => ({
    area: item.area,
    provider: item.recommendation?.provider ?? null,
    providerRecordId: item.recommendation?.provider_record_id ?? null,
    taskContent: item.recommendation?.title ?? null,
  }));
}


export function recommendationChanges(
  previousSnapshots: RecommendationSnapshot[],
  currentItems: TaskAreaRecommendation[],
): RecommendationChange[] {
  return currentItems.flatMap((current) => {
    const recommendation = current.recommendation;
    const previous = previousSnapshots.find((snapshot) => snapshot.area === current.area);
    if (!previous || !recommendation || sameRecommendation(previous, recommendation.provider, recommendation.provider_record_id)) {
      return [];
    }
    return [{
      area: current.area,
      previous: previous.taskContent ?? "No recommendation",
      current: recommendation.title,
      reason: recommendation.explanation,
    }];
  });
}


function sameRecommendation(snapshot: RecommendationSnapshot, provider: string, providerRecordId: string): boolean {
  return snapshot.provider === provider && snapshot.providerRecordId === providerRecordId;
}
