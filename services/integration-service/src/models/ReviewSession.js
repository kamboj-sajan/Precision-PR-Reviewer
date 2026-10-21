import mongoose from 'mongoose';

const reviewCommentSchema = new mongoose.Schema({
  filePath: { type: String, required: true },
  lineNumber: { type: Number, default: 1 },
  severity: {
    type: String,
    enum: ['INFO', 'WARNING', 'CRITICAL', 'SUGGESTION'],
    default: 'INFO',
  },
  category: {
    type: String,
    enum: ['SECURITY', 'PERFORMANCE', 'STYLE', 'SYNTAX', 'PRECISION'],
    default: 'PRECISION',
  },
  comment: { type: String, required: true },
  suggestedCode: { type: String },
  contextSnippet: { type: String },
});

const reviewSessionSchema = new mongoose.Schema(
  {
    repository: {
      owner: { type: String, required: true },
      name: { type: String, required: true },
      fullName: { type: String, required: true },
    },
    pullNumber: { type: Number, required: true },
    title: { type: String, default: '' },
    action: { type: String, default: 'opened' },
    sender: { type: String, default: 'anonymous' },
    baseRef: { type: String, default: 'main' },
    headRef: { type: String, default: '' },
    headSha: { type: String, default: '' },
    diffSnippet: { type: String, default: '' },
    diffLength: { type: Number, default: 0 },
    status: {
      type: String,
      enum: ['pending', 'processing', 'completed', 'failed'],
      default: 'pending',
    },
    reviewResult: {
      summary: { type: String },
      verdict: {
        type: String,
        enum: ['APPROVE', 'REQUEST_CHANGES', 'COMMENT'],
        default: 'COMMENT',
      },
      confidenceScore: { type: Number, default: 0.0 },
      retrievedContextCount: { type: Number, default: 0 },
      comments: [reviewCommentSchema],
    },
    errorMessage: { type: String },
  },
  {
    timestamps: true,
  }
);

reviewSessionSchema.index({ 'repository.fullName': 1, pullNumber: 1 });
reviewSessionSchema.index({ status: 1, createdAt: -1 });

export const ReviewSession = mongoose.model('ReviewSession', reviewSessionSchema);
