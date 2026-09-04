import torch

from data import build_model, label_to_query
from train import evaluate


def test_model_output_shape():
    model = build_model(num_classes=101, pretrained=False)
    logits = model(torch.zeros(2, 3, 224, 224))
    assert logits.shape == (2, 101)


def test_label_to_query_replaces_underscores():
    assert label_to_query("chicken_curry") == "chicken curry"
    assert label_to_query("pizza") == "pizza"


def test_evaluate_top1_and_top3():
    # 4 classes, batch of 3. Construct logits where the true class is
    # known to rank 1st, 3rd, and outside the top 3, respectively.
    logits = torch.tensor([
        [5.0, 1.0, 1.0, 1.0],  # label 0 is top-1 -> counts for both
        [1.0, 1.0, 5.0, 2.0],  # label 3 ranks 3rd -> top-3 only
        [5.0, 4.0, 3.0, 1.0],  # label 3 ranks 4th -> neither
    ])
    labels = torch.tensor([0, 3, 3])

    class DummyLoader:
        def __iter__(self):
            yield logits, labels

    class DummyModel(torch.nn.Module):
        def forward(self, x):
            return logits

        def eval(self):
            return self

    top1, top3 = evaluate(DummyModel(), DummyLoader(), torch.device("cpu"))
    assert top1 == 1 / 3
    assert top3 == 2 / 3
