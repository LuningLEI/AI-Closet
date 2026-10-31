import SwiftUI

struct CategoryEditor: View {
    @EnvironmentObject private var appSettings: AppSettings
    @ObservedObject var viewModel: ProfileViewModel
    @State private var newCategory = ""
    @State private var expandedCategories:Set<String> = []

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Categories & subcategories")
                .font(.caption.weight(.bold)).textCase(.uppercase).foregroundStyle(.secondary)
            VStack(spacing:0) {
                ForEach(viewModel.selectedCategories,id:\.self) { category in
                    DisclosureGroup(isExpanded:Binding(
                        get:{ expandedCategories.contains(category) },
                        set:{ expanded in
                            if expanded { expandedCategories.insert(category) }
                            else { expandedCategories.remove(category) }
                        })) {
                        EditableCatalogOptions(
                            title:"Subcategories",
                            options:Binding(
                                get:{ viewModel.catalogSubtypes[category] ?? ["Unknown"] },
                                set:{ viewModel.catalogSubtypes[category]=$0 }),
                            protectedOptions:["Unknown"])
                            .padding(.leading,20).padding(.vertical,10)
                    } label: {
                        HStack {
                            Text(category).font(.headline)
                            Spacer()
                            Button(role:.destructive) { removeCategory(category) } label: {
                                Image(systemName:"trash").font(.subheadline)
                            }.buttonStyle(.plain)
                        }.padding(.vertical,12)
                    }
                    if category != viewModel.selectedCategories.last { Divider() }
                }
            }
            .padding(.horizontal,14)
            .background(Color(.secondarySystemBackground),in:RoundedRectangle(cornerRadius:16))

            HStack {
                TextField("Add category",text:$newCategory).textFieldStyle(.roundedBorder)
                Button(appSettings.text("common.add")) { addCategory() }
            }

            EditableCatalogOptions(title:"Colors",options:$viewModel.catalogColors,protectedOptions:["Unknown"])
            EditableCatalogOptions(title:"Occasions",options:$viewModel.catalogOccasions)
            EditableCatalogOptions(title:"Styles",options:$viewModel.catalogStyles)
            EditableCatalogOptions(title:"Seasons",options:$viewModel.catalogSeasons)
            EditableCatalogOptions(title:"Garment lengths",options:$viewModel.catalogLengths)
            EditableCatalogOptions(title:"Sleeve lengths",options:$viewModel.catalogSleeveLengths)
        }
    }

    private func addCategory() {
        let value=newCategory.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !value.isEmpty,!viewModel.selectedCategories.contains(value) else { return }
        viewModel.selectedCategories.append(value)
        viewModel.catalogSubtypes[value]=["Unknown"]
        if !viewModel.customCategories.contains(value) {
            viewModel.customCategories.append(value)
        }
        expandedCategories.insert(value);newCategory=""
    }

    private func removeCategory(_ category:String) {
        viewModel.selectedCategories.removeAll{$0==category}
        viewModel.customCategories.removeAll{$0==category}
        viewModel.catalogSubtypes.removeValue(forKey:category)
        expandedCategories.remove(category)
    }
}
struct EditableCatalogOptions:View {
    let title:String
    @Binding var options:[String]
    var protectedOptions:Set<String>=[]
    @State private var expanded=false
    @State private var newValue=""
    var body:some View {
        DisclosureGroup(isExpanded:$expanded) {
            VStack(spacing:8) {
                ForEach(options,id:\.self) { option in
                    HStack {
                        Text(option);Spacer()
                        if !protectedOptions.contains(option) {
                            Button(role:.destructive) { options.removeAll{$0==option} } label: {
                                Image(systemName:"minus.circle.fill")
                            }.buttonStyle(.plain)
                        }
                    }.padding(.vertical,4)
                }
                HStack {
                    TextField("Add \(title.lowercased().dropLast(title.hasSuffix("s") ? 1 : 0))",text:$newValue)
                        .textFieldStyle(.roundedBorder)
                    Button("Add") {
                        let value=newValue.trimmingCharacters(in:.whitespacesAndNewlines)
                        guard !value.isEmpty,!options.contains(value) else { return }
                        options.append(value);newValue=""
                    }
                }
            }.padding(.top,10)
        } label: {
            HStack { Text(title).font(.headline);Spacer();Text("\(options.count)").foregroundStyle(.secondary) }
        }
        .padding(14)
        .background(Color(.secondarySystemBackground),in:RoundedRectangle(cornerRadius:16))
    }
}
